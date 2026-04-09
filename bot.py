import discord
from discord.ext import commands, tasks
import asyncio
import logging
import os
import sys
from dotenv import load_dotenv
from discord import ui, app_commands
from datetime import datetime, timedelta

# ボイス接続: PyNaCl + davey（Discord の DAVE 暗号化。無いと接続が 4017 で拒否される）
try:
    import nacl
    import davey  # noqa: F401
except ImportError:
    print("エラー: ボイス機能に PyNaCl と davey が必要です。", file=sys.stderr)
    print("  例: python3 -m pip install --user --break-system-packages 'discord.py[voice]>=2.7.1'", file=sys.stderr)
    sys.exit(1)

load_dotenv()
from vc_channel_rename import (
    ensure_pomodoro_prefix_name,
    is_vc_channel_rename_enabled,
    restore_vc_channel_if_pomodoro_tag,
    restore_vc_channel_name_by_id,
)

TOKEN = os.getenv("DISCORD_TOKEN")
# エラー・レート制限の通知先チャンネルID（ボットに「メッセージを送信」権限を付与すること）
_error_channel_id_str = os.getenv("ERROR_CHANNEL_ID", "").strip()
ERROR_CHANNEL_ID = int(_error_channel_id_str) if _error_channel_id_str.isdigit() else None
GUILD_TIMER = {}  # サーバーごとのループタイマー管理
GUILD_PAUSED = {}  # サーバーごとの一時停止状態管理
GUILD_REMAINING = {}  # サーバーごとの残り時間管理

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True


class DiscordRateLimitChannelHandler(logging.Handler):
    """discord.http のレート制限 (429) を ERROR_CHANNEL_ID のチャンネルに通知する。"""

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.WARNING:
            return
        msg = record.getMessage()
        if "429" not in msg and "rate limit" not in msg.lower():
            return
        if not ERROR_CHANNEL_ID:
            return
        text = f"⚠️ ポモドーロボット レート制限\n**discord.http**\n```\n{msg}\n```"
        bot = globals().get("bot")
        if bot and bot.is_ready():
            try:
                ch = bot.get_channel(ERROR_CHANNEL_ID)
                if ch:
                    asyncio.run_coroutine_threadsafe(ch.send(text[:2000]), bot.loop).result(timeout=10)
            except Exception:
                pass


if ERROR_CHANNEL_ID:
    logging.getLogger("discord.http").addHandler(DiscordRateLimitChannelHandler())


async def notify_error(context: str, error: Exception) -> None:
    """エラーをログ出力し、設定されていれば ERROR_CHANNEL_ID のチャンネルに通知する。
    Unknown Message (10008) は通知・ログともスキップ（ephemeral メッセージが閉じられた等でよくあるため）。
    """
    # 10008 Unknown Message = 編集対象メッセージが存在しない（ユーザーが閉じた等）。ログ・通知ともスキップ。
    if getattr(error, "code", None) == 10008:
        return
    msg = f"{context}: {type(error).__name__}: {error}"
    print(msg, file=sys.stderr)
    if not ERROR_CHANNEL_ID:
        return
    text = f"⚠️ ポモドーロボット エラー\n**{context}**\n```\n{type(error).__name__}: {error}\n```"
    bot = globals().get("bot")
    if bot and bot.is_ready():
        try:
            ch = bot.get_channel(ERROR_CHANNEL_ID)
            if ch:
                await ch.send(text[:2000])
        except Exception as e:
            print(f"エラー通知チャンネル送信失敗: {e}", file=sys.stderr)


class PomodoroView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.start_button = None
        self.pause_button = None

    @discord.ui.button(label="開始", style=discord.ButtonStyle.green, emoji="▶️", custom_id="start_pomodoro")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild_id in GUILD_TIMER:
            await interaction.response.send_message('⚠️ すでにポモドーロ中です。終了ボタンで止めてから再度試してください。', ephemeral=True)
            return

        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message('❌ VCに入ってから実行してください。', ephemeral=True)
            return

        # チャンネル名変更を使う場合のみ「チャンネル管理」が必要
        bot_member = interaction.guild.get_member(interaction.client.user.id)
        if is_vc_channel_rename_enabled() and not bot_member.guild_permissions.manage_channels:
            await interaction.response.send_message('❌ ボットにチャンネル管理の権限がありません。サーバー設定で権限を付与してください。', ephemeral=True)
            return

        channel = interaction.user.voice.channel

        # インタラクションは3秒以内に応答必須。届いた時点で期限切れ(10062)の場合は defer せず続行
        can_use_followup = True
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.NotFound as e:
            if getattr(e, "code", None) == 10062:  # Unknown interaction（届く前に期限切れ）
                can_use_followup = False
            else:
                raise

        # すでにVCに接続している場合は切断
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()

        vc = await channel.connect()
        try:
            if can_use_followup:
                await interaction.followup.send('🔁 ポモドーロタイマー開始!25分作業 / 5分休憩を繰り返します', ephemeral=True)
            else:
                await interaction.channel.send('🔁 ポモドーロタイマー開始!25分作業 / 5分休憩を繰り返します')
        except discord.HTTPException as e:
            await notify_error("開始メッセージ送信", e)

        # 開始ボタンを非アクティブに
        button.disabled = True
        try:
            await interaction.message.edit(view=self)
        except discord.NotFound as e:
            await notify_error("メッセージの編集（開始時）", e)
        except Exception as e:
            await notify_error("メッセージの編集（開始時）", e)

        GUILD_PAUSED[interaction.guild_id] = False
        GUILD_REMAINING[interaction.guild_id] = 25 * 60  # 25分を秒で設定

        # 既に(ポモ中)が付いている場合は外した名前を元名として使う（二重付与・比較ミス防止）
        _raw_name = channel.name
        if _raw_name.startswith("(ポモ中)"):
            original_channel_name = _raw_name.replace("(ポモ中)", "", 1).strip() or _raw_name
        else:
            original_channel_name = _raw_name
        channel_id = channel.id
        # チャンネル名変更エラーをユーザーに1回だけ通知したか（スパム防止）
        channel_rename_error_told = [False]
        text_channel = interaction.channel

        async def loop_task():
            try:
                while True:
                    # 作業時間（25分）：現在のチャンネル名をAPIから取得してから付与
                    try:
                        await ensure_pomodoro_prefix_name(
                            interaction.guild, channel_id, original_channel_name
                        )
                    except Exception as e:
                        await notify_error("チャンネル名変更（作業開始時）", e)
                        if not channel_rename_error_told[0] and text_channel:
                            try:
                                await text_channel.send("⚠️ VC名の変更ができませんでした（権限不足など）。タイマー・音声はそのまま続行します。")
                                channel_rename_error_told[0] = True
                            except Exception:
                                pass
                    
                    try:
                        await play_mp3(vc, 'start.mp3')
                    except Exception as e:
                        await notify_error("音声再生 start.mp3", e)
                        # エラーが発生しても続行
                    
                    GUILD_REMAINING[interaction.guild_id] = 25 * 60
                    while GUILD_REMAINING[interaction.guild_id] > 0:
                        if GUILD_PAUSED.get(interaction.guild_id):
                            await asyncio.sleep(1)
                            continue
                        await asyncio.sleep(1)
                        GUILD_REMAINING[interaction.guild_id] -= 1
                    
                    # 休憩中も VC 名は (ポモ中) のまま（休憩ごとに PATCH すると Discord のチャンネル更新レート制限 429 に当たりやすい）
                    try:
                        await play_mp3(vc, 'break.mp3')
                    except Exception as e:
                        await notify_error("音声再生 break.mp3", e)
                        # エラーが発生しても続行
                    
                    GUILD_REMAINING[interaction.guild_id] = 5 * 60
                    while GUILD_REMAINING[interaction.guild_id] > 0:
                        if GUILD_PAUSED.get(interaction.guild_id):
                            await asyncio.sleep(1)
                            continue
                        await asyncio.sleep(1)
                        GUILD_REMAINING[interaction.guild_id] -= 1
            except asyncio.CancelledError:
                await vc.disconnect()
                try:
                    await restore_vc_channel_name_by_id(
                        interaction.guild, channel_id, original_channel_name
                    )
                except Exception as e:
                    await notify_error("チャンネル名復元（停止時）", e)
                return

        task = asyncio.create_task(loop_task())
        GUILD_TIMER[interaction.guild_id] = task

    @discord.ui.button(label="一時停止", style=discord.ButtonStyle.grey, emoji="⏸️", custom_id="pause_pomodoro")
    async def pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild_id not in GUILD_TIMER:
            await interaction.response.send_message('⏸️ タイマーは動いていません。', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        remaining_minutes = GUILD_REMAINING[interaction.guild_id] // 60
        remaining_seconds = GUILD_REMAINING[interaction.guild_id] % 60

        if GUILD_PAUSED.get(interaction.guild_id):
            GUILD_PAUSED[interaction.guild_id] = False
            button.label = "一時停止"
            button.emoji = "⏸️"
            button.style = discord.ButtonStyle.grey
            info = f'▶️ タイマーを再開しました。残り時間: {remaining_minutes}分{remaining_seconds}秒'
            err_ctx = "メッセージの編集（一時停止→再開）"
        else:
            GUILD_PAUSED[interaction.guild_id] = True
            button.label = "再開"
            button.emoji = "▶️"
            button.style = discord.ButtonStyle.green
            info = f'⏸️ タイマーを一時停止しました。残り時間: {remaining_minutes}分{remaining_seconds}秒'
            err_ctx = "メッセージの編集（一時停止）"

        try:
            await interaction.edit_original_response(view=self)
        except discord.NotFound as e:
            await notify_error(err_ctx, e)
        except Exception as e:
            await notify_error(err_ctx, e)
        try:
            await interaction.followup.send(info, ephemeral=True)
        except discord.HTTPException as e:
            await notify_error("followup送信（一時停止/再開）", e)

    async def _do_stop(self, interaction: discord.Interaction):
        """停止・終了の共通処理。defer 済みであること。"""
        task = GUILD_TIMER.get(interaction.guild_id)
        if not task:
            return False

        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=6.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

        GUILD_TIMER.pop(interaction.guild_id, None)
        GUILD_PAUSED.pop(interaction.guild_id, None)
        GUILD_REMAINING.pop(interaction.guild_id, None)

        vc = interaction.guild.voice_client
        if vc and vc.channel:
            try:
                await restore_vc_channel_if_pomodoro_tag(vc.channel)
            except Exception as e:
                await notify_error("チャンネル名復元（_do_stop）", e)
        if vc:
            try:
                await vc.disconnect()
            except Exception as e:
                await notify_error("VC切断", e)

        for child in self.children:
            if child.custom_id == "start_pomodoro":
                child.disabled = False
            elif child.custom_id == "pause_pomodoro":
                child.label = "一時停止"
                child.emoji = "⏸️"
                child.style = discord.ButtonStyle.grey
        try:
            await interaction.message.edit(view=self)
        except discord.NotFound as e:
            await notify_error("メッセージの編集（停止後）", e)
        except Exception as e:
            await notify_error("メッセージの編集（停止後）", e)

        try:
            await interaction.followup.send('🛑 ポモドーロを停止しました。', ephemeral=True)
        except discord.HTTPException as e:
            await notify_error("followup送信", e)
            try:
                await interaction.channel.send('🛑 ポモドーロを停止しました。')
            except Exception:
                pass
        return True

    @discord.ui.button(label="終了", style=discord.ButtonStyle.red, emoji="🔚", custom_id="end_pomodoro")
    async def end_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild_id not in GUILD_TIMER:
            await interaction.response.send_message('🔚 タイマーは動いていません。', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        if not await self._do_stop(interaction):
            await interaction.followup.send('🔚 タイマーは動いていません。', ephemeral=True)

class PomodoroBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)
        self.initial_extensions = []

    async def setup_hook(self):
        print("Syncing commands...")
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} command(s)")
        except Exception as e:
            await notify_error("コマンド同期", e)

    async def on_ready(self):
        print(f'✅ Bot ready: {self.user}')
        self.add_view(PomodoroView())

bot = PomodoroBot()

@bot.tree.command(
    name="pomodoro",
    description="ポモドーロタイマーを開始します"
)
async def pomodoro(interaction: discord.Interaction):
    view = PomodoroView()
    await interaction.response.send_message(
        "ポモドーロタイマー\n▶️ 開始: タイマーを開始\n⏸️ 一時停止: 一時停止/再開\n🔚 終了: タイマーを停止",
        view=view,
        ephemeral=True
    )

async def play_mp3(vc: discord.VoiceClient, filename: str):
    # 接続完了直後のわずかな遅延で is_connected が False のときがあるため短時間待つ
    for _ in range(100):
        if vc.is_connected():
            break
        await asyncio.sleep(0.1)
    if not vc.is_connected():
        raise discord.ClientException("Not connected to voice.")

    source = discord.FFmpegPCMAudio(source=os.path.join('sounds', filename))
    vc.play(source)
    while vc.is_playing():
        await asyncio.sleep(1)

bot.run(TOKEN)

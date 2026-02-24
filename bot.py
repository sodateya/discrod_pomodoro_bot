import discord
from discord.ext import commands, tasks
import asyncio
import json
import logging
import os
import sys
import urllib.request
from dotenv import load_dotenv
from discord import ui, app_commands
from datetime import datetime, timedelta

# ボイス接続に PyNaCl 必須（venv で pip install PyNaCl 済みの Python で起動すること）
try:
    import nacl
except ImportError:
    print("エラー: ボイス機能に PyNaCl が必要です。", file=sys.stderr)
    print("  venv で起動: ./venv/bin/python bot.py", file=sys.stderr)
    print("  または: pip install PyNaCl のあと python bot.py", file=sys.stderr)
    sys.exit(1)

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
ERROR_WEBHOOK_URL = os.getenv("ERROR_WEBHOOK_URL", "").strip()
# エラー通知先チャンネルID（ボットの「メッセージを送信」権限で投稿。Webhook の代わりに使える）
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


def _send_webhook_sync(url: str, text: str) -> None:
    try:
        data = json.dumps({"content": text[:2000]}).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST", headers={"Content-Type": "application/json; charset=utf-8"}
        )
        with urllib.request.urlopen(req, timeout=10) as res:
            pass  # 2xx で成功
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace").strip()
        except Exception:
            pass
        print(f"Webhook送信失敗: HTTP {e.code} {e.reason}", file=sys.stderr)
        if body:
            print(f"  → Discord の応答: {body[:300]}", file=sys.stderr)
        if e.code == 403:
            print("  → Webhook が削除されたか、URL のトークンが無効です。チャンネル設定で Webhook を新規作成し、.env の URL を貼り直してください。", file=sys.stderr)
        elif e.code == 404:
            print("  → Webhook が存在しません（削除されたか URL が間違っています）。", file=sys.stderr)
    except Exception as e:
        print(f"Webhook送信失敗: {e}", file=sys.stderr)
        if "403" in str(e):
            print("  → ERROR_WEBHOOK_URL が無効です。Discord のチャンネル設定で Webhook を確認・再生成し、.env を更新してください。", file=sys.stderr)


class DiscordRateLimitWebhookHandler(logging.Handler):
    """discord.http のレート制限 (429) をチャンネルまたは Webhook に通知する。"""

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.WARNING:
            return
        msg = record.getMessage()
        if "429" not in msg and "rate limit" not in msg.lower():
            return
        text = f"⚠️ ポモドーロボット レート制限\n**discord.http**\n```\n{msg}\n```"
        bot = globals().get("bot")
        if ERROR_CHANNEL_ID and bot and bot.is_ready():
            try:
                ch = bot.get_channel(ERROR_CHANNEL_ID)
                if ch:
                    asyncio.run_coroutine_threadsafe(ch.send(text[:2000]), bot.loop).result(timeout=10)
                    return
            except Exception:
                pass
        if ERROR_WEBHOOK_URL:
            _send_webhook_sync(ERROR_WEBHOOK_URL, text)


# レート制限 (429) を通知（チャンネル or Webhook）
if ERROR_CHANNEL_ID or ERROR_WEBHOOK_URL:
    logging.getLogger("discord.http").addHandler(DiscordRateLimitWebhookHandler())


async def notify_error(context: str, error: Exception) -> None:
    """エラーをログ出力し、設定されていれば ERROR_CHANNEL_ID または Webhook に通知する。
    Unknown Message (10008) は通知・ログともスキップ（ephemeral メッセージが閉じられた等でよくあるため）。
    """
    # 10008 Unknown Message = 編集対象メッセージが存在しない（ユーザーが閉じた等）。ログ・通知ともスキップ。
    if getattr(error, "code", None) == 10008:
        return
    msg = f"{context}: {type(error).__name__}: {error}"
    print(msg, file=sys.stderr)
    text = f"⚠️ ポモドーロボット エラー\n**{context}**\n```\n{type(error).__name__}: {error}\n```"
    # チャンネルIDが設定されていればボットの権限で送信（Webhook 不要）
    bot = globals().get("bot")
    if ERROR_CHANNEL_ID and bot and bot.is_ready():
        try:
            ch = bot.get_channel(ERROR_CHANNEL_ID)
            if ch:
                await ch.send(text[:2000])
                return
        except Exception as e:
            print(f"エラー通知チャンネル送信失敗: {e}", file=sys.stderr)
    if ERROR_WEBHOOK_URL:
        try:
            await asyncio.to_thread(_send_webhook_sync, ERROR_WEBHOOK_URL, text)
        except Exception as e:
            print(f"Webhook送信失敗: {e}", file=sys.stderr)
            if "403" in str(e):
                print("  → Webhook URL が無効か削除されています。Discord のチャンネル設定で Webhook を確認・再生成してください。", file=sys.stderr)


class PomodoroView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.start_button = None
        self.pause_button = None
        self.stop_button = None

    @discord.ui.button(label="開始", style=discord.ButtonStyle.green, emoji="▶️", custom_id="start_pomodoro")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild_id in GUILD_TIMER:
            await interaction.response.send_message('⚠️ すでにポモドーロ中です。停止ボタンで止めてから再度試してください。', ephemeral=True)
            return

        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message('❌ VCに入ってから実行してください。', ephemeral=True)
            return

        # ボットの権限チェック
        bot_member = interaction.guild.get_member(interaction.client.user.id)
        if not bot_member.guild_permissions.manage_channels:
            await interaction.response.send_message('❌ ボットにチャンネル管理の権限がありません。サーバー設定で権限を付与してください。', ephemeral=True)
            return

        channel = interaction.user.voice.channel

        # インタラクションは3秒以内に応答必須。VC接続は時間がかかるため先に defer
        await interaction.response.defer(ephemeral=True)

        # すでにVCに接続している場合は切断
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()

        vc = await channel.connect()
        try:
            await interaction.followup.send('🔁 ポモドーロタイマー開始!25分作業 / 5分休憩を繰り返します', ephemeral=True)
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
                        current = interaction.guild.get_channel(channel_id)
                        if current is None:
                            current = await interaction.guild.fetch_channel(channel_id)
                        current_name = current.name if current else ""
                        new_name = f"(ポモ中){original_channel_name}"
                        if current_name != new_name:
                            await current.edit(name=new_name)
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
                    
                    # 休憩時間（5分）
                    try:
                        ch = interaction.guild.get_channel(channel_id) or await interaction.guild.fetch_channel(channel_id)
                        if ch:
                            await ch.edit(name=original_channel_name)
                    except Exception as e:
                        await notify_error("チャンネル名変更（休憩開始時）", e)
                        if not channel_rename_error_told[0] and text_channel:
                            try:
                                await text_channel.send("⚠️ VC名の変更ができませんでした（権限不足など）。タイマー・音声はそのまま続行します。")
                                channel_rename_error_told[0] = True
                            except Exception:
                                pass
                    
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
                    ch = interaction.guild.get_channel(channel_id) or await interaction.guild.fetch_channel(channel_id)
                    if ch:
                        await ch.edit(name=original_channel_name)
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

        if GUILD_PAUSED.get(interaction.guild_id):
            GUILD_PAUSED[interaction.guild_id] = False
            remaining_minutes = GUILD_REMAINING[interaction.guild_id] // 60
            remaining_seconds = GUILD_REMAINING[interaction.guild_id] % 60
            # ボタンの状態を一時停止に戻す
            button.label = "一時停止"
            button.emoji = "⏸️"
            button.style = discord.ButtonStyle.grey
            try:
                await interaction.message.edit(view=self)
            except discord.NotFound as e:
                await notify_error("メッセージの編集（一時停止→再開）", e)
            except Exception as e:
                await notify_error("メッセージの編集（一時停止→再開）", e)
            await interaction.response.send_message(f'▶️ タイマーを再開しました。残り時間: {remaining_minutes}分{remaining_seconds}秒', ephemeral=True)
        else:
            GUILD_PAUSED[interaction.guild_id] = True
            remaining_minutes = GUILD_REMAINING[interaction.guild_id] // 60
            remaining_seconds = GUILD_REMAINING[interaction.guild_id] % 60
            # ボタンの状態を再開に変更
            button.label = "再開"
            button.emoji = "▶️"
            button.style = discord.ButtonStyle.green
            try:
                await interaction.message.edit(view=self)
            except discord.NotFound as e:
                await notify_error("メッセージの編集（一時停止）", e)
            except Exception as e:
                await notify_error("メッセージの編集（一時停止）", e)
            await interaction.response.send_message(f'⏸️ タイマーを一時停止しました。残り時間: {remaining_minutes}分{remaining_seconds}秒', ephemeral=True)

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
        if vc and vc.channel and "(ポモ中)" in vc.channel.name:
            try:
                original_name = vc.channel.name.replace("(ポモ中)", "").strip()
                await vc.channel.edit(name=original_name)
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

    @discord.ui.button(label="停止", style=discord.ButtonStyle.red, emoji="⏹️", custom_id="stop_pomodoro")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild_id not in GUILD_TIMER:
            await interaction.response.send_message('⏹️ タイマーは動いていません。', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        if not await self._do_stop(interaction):
            await interaction.followup.send('⏹️ タイマーは動いていません。', ephemeral=True)

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
        "ポモドーロタイマー\n▶️ 開始: タイマーを開始\n⏸️ 一時停止: 一時停止/再開\n⏹️ 停止 / 🔚 終了: タイマーを停止",
        view=view,
        ephemeral=True
    )

async def play_mp3(vc: discord.VoiceClient, filename: str):
    source = discord.FFmpegPCMAudio(source=os.path.join('sounds', filename))
    vc.play(source)
    while vc.is_playing():
        await asyncio.sleep(1)

bot.run(TOKEN)

import discord
from discord.ext import commands, tasks
import asyncio
import os
import sys
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
GUILD_TIMER = {}  # サーバーごとのループタイマー管理
GUILD_PAUSED = {}  # サーバーごとの一時停止状態管理
GUILD_REMAINING = {}  # サーバーごとの残り時間管理

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True

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
        
        # すでにVCに接続している場合は切断
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()
        
        vc = await channel.connect()
        await interaction.response.send_message('🔁 ポモドーロタイマー開始!25分作業 / 5分休憩を繰り返します', ephemeral=True)

        # 開始ボタンを非アクティブに
        button.disabled = True
        try:
            await interaction.message.edit(view=self)
        except discord.NotFound:
            print("メッセージの編集に失敗しました（メッセージが見つかりません）")
        except Exception as e:
            print(f"メッセージの編集に失敗しました: {e}")

        GUILD_PAUSED[interaction.guild_id] = False
        GUILD_REMAINING[interaction.guild_id] = 25 * 60  # 25分を秒で設定

        async def loop_task():
            try:
                original_channel_name = channel.name
                while True:
                    # 作業時間（25分）
                    try:
                        if channel.name != f"(ポモ中){original_channel_name}":
                            await channel.edit(name=f"(ポモ中){original_channel_name}")
                    except Exception as e:
                        print(f"チャンネル名変更エラー: {e}")
                        # エラーが発生しても続行
                    
                    try:
                        await play_mp3(vc, 'start.mp3')
                    except Exception as e:
                        print(f"音声再生エラー: {e}")
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
                        await channel.edit(name=original_channel_name)
                    except Exception as e:
                        print(f"チャンネル名変更エラー: {e}")
                        # エラーが発生しても続行
                    
                    try:
                        await play_mp3(vc, 'break.mp3')
                    except Exception as e:
                        print(f"音声再生エラー: {e}")
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
                    await channel.edit(name=original_channel_name)
                except Exception as e:
                    print(f"チャンネル名変更エラー: {e}")
                    # エラーが発生しても続行
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
            except discord.NotFound:
                print("メッセージの編集に失敗しました（メッセージが見つかりません）")
            except Exception as e:
                print(f"メッセージの編集に失敗しました: {e}")
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
            except discord.NotFound:
                print("メッセージの編集に失敗しました（メッセージが見つかりません）")
            except Exception as e:
                print(f"メッセージの編集に失敗しました: {e}")
            await interaction.response.send_message(f'⏸️ タイマーを一時停止しました。残り時間: {remaining_minutes}分{remaining_seconds}秒', ephemeral=True)

    @discord.ui.button(label="停止", style=discord.ButtonStyle.red, emoji="⏹️", custom_id="stop_pomodoro")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        task = GUILD_TIMER.get(interaction.guild_id)
        if not task:
            await interaction.response.send_message('⏹️ タイマーは動いていません。', ephemeral=True)
            return

        # 3秒以内に必ず応答する（先に defer してから後で followup）
        await interaction.response.defer(ephemeral=True)

        task.cancel()
        del GUILD_TIMER[interaction.guild_id]
        del GUILD_PAUSED[interaction.guild_id]
        del GUILD_REMAINING[interaction.guild_id]

        # ボットが接続しているVCのチャンネル名を復元（ユーザーのVCではない）
        vc = interaction.guild.voice_client
        if vc and vc.channel and "(ポモ中)" in vc.channel.name:
            try:
                original_name = vc.channel.name.replace("(ポモ中)", "").strip()
                await vc.channel.edit(name=original_name)
            except Exception as e:
                print(f"チャンネル名変更エラー: {e}")
        if vc:
            try:
                await vc.disconnect()
            except Exception as e:
                print(f"VC切断エラー: {e}")

        # 開始ボタンを再度アクティブに
        for child in self.children:
            if child.custom_id == "start_pomodoro":
                child.disabled = False
            elif child.custom_id == "pause_pomodoro":
                child.label = "一時停止"
                child.emoji = "⏸️"
                child.style = discord.ButtonStyle.grey
        try:
            await interaction.message.edit(view=self)
        except discord.NotFound:
            print("メッセージの編集に失敗しました（メッセージが見つかりません）")
        except Exception as e:
            print(f"メッセージの編集に失敗しました: {e}")

        await interaction.followup.send('🛑 ポモドーロを停止しました。', ephemeral=True)

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
            print(f"Failed to sync commands: {e}")

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
        "ポモドーロタイマー\n▶️ 開始ボタン: タイマーを開始\n⏸️ 一時停止ボタン: タイマーを一時停止/再開\n⏹️ 停止ボタン: タイマーを停止",
        view=view,
        ephemeral=True
    )

async def play_mp3(vc: discord.VoiceClient, filename: str):
    source = discord.FFmpegPCMAudio(source=os.path.join('sounds', filename))
    vc.play(source)
    while vc.is_playing():
        await asyncio.sleep(1)

bot.run(TOKEN)

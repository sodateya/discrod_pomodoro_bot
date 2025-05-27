import discord
from discord.ext import commands, tasks
import asyncio
import os
from dotenv import load_dotenv
from discord import ui, app_commands
from datetime import datetime, timedelta
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_TIMER = {}  # サーバーごとのループタイマー管理
GUILD_VIEWS = {}  # サーバーごとのビュー管理

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True

class PomodoroView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.start_button = None
        self.stop_button = None

    @discord.ui.button(label="開始", style=discord.ButtonStyle.green, emoji="▶️", custom_id="start_pomodoro")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        print("開始ボタンが押されました")
        if interaction.guild_id in GUILD_TIMER:
            print("すでにタイマーが実行中です")
            await interaction.response.send_message('⚠️ すでにポモドーロ中です。停止ボタンで止めてから再度試してください。', ephemeral=True)
            return

        if not interaction.user.voice or not interaction.user.voice.channel:
            print("ユーザーがVCに入っていません")
            await interaction.response.send_message('❌ VCに入ってから実行してください。', ephemeral=True)
            return

        print("VCに接続を試みます")
        channel = interaction.user.voice.channel
        try:
            vc = await channel.connect()
            print("VC接続成功")
        except Exception as e:
            print(f"VC接続エラー: {e}")
            await interaction.response.send_message('❌ 音声接続に失敗しました。', ephemeral=True)
            return

        # メッセージを送信して保存
        await interaction.response.send_message(
            '🔁 ポモドーロタイマー開始!25分作業 / 5分休憩を繰り返します',
            view=self,
            ephemeral=True
        )
        message = await interaction.original_response()
        print("タイマー開始メッセージを送信")

        # ボタンの状態を保存
        self.start_button = button
        self.stop_button = [b for b in self.children if b.custom_id == "stop_pomodoro"][0]
        GUILD_VIEWS[interaction.guild_id] = self
        print("ボタンの状態を保存")

        async def loop_task():
            try:
                print("ループタスク開始")
                while True:
                    # 作業時間（25分）
                    end_time = datetime.now() + timedelta(minutes=25)
                    self.start_button.label = f"作業中: 残り25分"
                    self.start_button.style = discord.ButtonStyle.green
                    try:
                        await message.edit(view=self)
                    except Exception as e:
                        print(f"メッセージ更新エラー: {e}")
                        return
                    print("作業時間開始")
                    
                    # 作業開始の音声を再生
                    print("作業開始の音声を再生")
                    await play_mp3(vc, 'start.mp3')
                    print("作業開始の音声再生完了")
                    
                    # 通知する残り時間のリスト
                    notify_times = [15, 10, 5, 1]
                    last_notified = 25  # 初期値は25分
                    
                    while datetime.now() < end_time:
                        remaining = (end_time - datetime.now()).total_seconds() / 60
                        # 残り時間が通知タイミングになったら更新
                        for notify_time in notify_times:
                            if remaining <= notify_time and last_notified > notify_time:
                                self.start_button.label = f"作業中: 残り{notify_time}分"
                                await message.edit(view=self)
                                last_notified = notify_time
                                break
                        await asyncio.sleep(1)

                    # 休憩時間（5分）
                    end_time = datetime.now() + timedelta(minutes=5)
                    self.start_button.label = f"休憩中: 残り5分"
                    self.start_button.style = discord.ButtonStyle.blurple
                    try:
                        await message.edit(view=self)
                    except Exception as e:
                        print(f"メッセージ更新エラー: {e}")
                        return
                    print("休憩時間開始")
                    
                    # 休憩開始の音声を再生
                    print("休憩開始の音声を再生")
                    await play_mp3(vc, 'break.mp3')
                    print("休憩開始の音声再生完了")
                    
                    # 通知する残り時間のリスト
                    notify_times = [4, 3, 2, 1]
                    last_notified = 5  # 初期値は5分
                    
                    while datetime.now() < end_time:
                        remaining = (end_time - datetime.now()).total_seconds() / 60
                        # 残り時間が通知タイミングになったら更新
                        for notify_time in notify_times:
                            if remaining <= notify_time and last_notified > notify_time:
                                self.start_button.label = f"休憩中: 残り{notify_time}分"
                                await message.edit(view=self)
                                last_notified = notify_time
                                break
                        await asyncio.sleep(1)

            except asyncio.CancelledError:
                print("ループタスクがキャンセルされました")
                await vc.disconnect()
                # ボタンを元の状態に戻す
                self.start_button.label = "開始"
                self.start_button.style = discord.ButtonStyle.green
                try:
                    await message.edit(view=self)
                except Exception as e:
                    print(f"メッセージ更新エラー: {e}")
                if interaction.guild_id in GUILD_VIEWS:
                    del GUILD_VIEWS[interaction.guild_id]
                return
            except Exception as e:
                print(f"ループタスクでエラーが発生: {e}")
                await vc.disconnect()
                return

        print("タスクを作成して開始")
        task = asyncio.create_task(loop_task())
        GUILD_TIMER[interaction.guild_id] = task
        print("タスクを保存")

    @discord.ui.button(label="停止", style=discord.ButtonStyle.red, emoji="⏹️", custom_id="stop_pomodoro")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        task = GUILD_TIMER.get(interaction.guild_id)
        if task:
            task.cancel()
            del GUILD_TIMER[interaction.guild_id]
            await interaction.response.send_message('🛑 ポモドーロを停止しました。', ephemeral=True)
        else:
            await interaction.response.send_message('⏹️ タイマーは動いていません。', ephemeral=True)

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
        "ポモドーロタイマー\n▶️ 開始ボタン: タイマーを開始\n⏹️ 停止ボタン: タイマーを停止",
        view=view,
        ephemeral=True
    )

async def play_mp3(vc: discord.VoiceClient, filename: str):
    # 現在のスクリプトのディレクトリを取得
    current_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(current_dir, 'sounds', filename)
    print(f"Playing sound file: {file_path}")
    print(f"File exists: {os.path.exists(file_path)}")
    try:
        source = discord.FFmpegPCMAudio(source=file_path)
        vc.play(source)
        print(f"Started playing: {filename}")
        while vc.is_playing():
            await asyncio.sleep(1)
        print(f"Finished playing: {filename}")
    except Exception as e:
        print(f"Error playing {filename}: {e}")
        print(f"Current working directory: {os.getcwd()}")

bot.run(TOKEN)

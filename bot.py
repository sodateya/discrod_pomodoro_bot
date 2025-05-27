import discord
from discord.ext import commands, tasks
import asyncio
import os
from dotenv import load_dotenv
from discord import ui, app_commands
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_TIMER = {}  # サーバーごとのループタイマー管理

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True

class PomodoroView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="開始", style=discord.ButtonStyle.green, emoji="▶️", custom_id="start_pomodoro")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild_id in GUILD_TIMER:
            await interaction.response.send_message('⚠️ すでにポモドーロ中です。停止ボタンで止めてから再度試してください。', ephemeral=True)
            return

        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message('❌ VCに入ってから実行してください。', ephemeral=True)
            return

        channel = interaction.user.voice.channel
        vc = await channel.connect()
        await interaction.response.send_message('🔁 ポモドーロタイマー開始!25分作業 / 5分休憩を繰り返します', ephemeral=True)

        async def loop_task():
            try:
                while True:
                    await play_mp3(vc, 'start.mp3')
                    await asyncio.sleep(25 * 60)
                    await play_mp3(vc, 'break.mp3')
                    await asyncio.sleep(5 * 60)
            except asyncio.CancelledError:
                await vc.disconnect()
                return

        task = asyncio.create_task(loop_task())
        GUILD_TIMER[interaction.guild_id] = task

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
    source = discord.FFmpegPCMAudio(source=os.path.join('sounds', filename))
    vc.play(source)
    while vc.is_playing():
        await asyncio.sleep(1)

bot.run(TOKEN)

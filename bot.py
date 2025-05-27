import discord
from discord.ext import commands, tasks
import asyncio
import os
from dotenv import load_dotenv
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_TIMER = {}  # サーバーごとのループタイマー管理

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'✅ Bot ready: {bot.user}')

async def play_mp3(vc: discord.VoiceClient, filename: str):
    source = discord.FFmpegPCMAudio(source=os.path.join('sounds', filename))
    vc.play(source)
    while vc.is_playing():
        await asyncio.sleep(1)

@bot.command()
async def pomodoro(ctx):
    if ctx.guild.id in GUILD_TIMER:
        await ctx.send('⚠️ すでにポモドーロ中です。`!stop` で止めてから再度試してください。')
        return

    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send('❌ VCに入ってから実行してください。')
        return

    channel = ctx.author.voice.channel
    vc = await channel.connect()
    await ctx.send('🔁 ポモドーロタイマー開始!25分作業 / 5分休憩を繰り返します')

    async def loop_task():
        try:
            while True:
                await ctx.send('🟢 作業開始!25分')
                await play_mp3(vc, 'start.mp3')
                await asyncio.sleep(25 * 60)
                await ctx.send('🟡 休憩開始!5分')
                await play_mp3(vc, 'break.mp3')
                await asyncio.sleep(5 * 60)
        except asyncio.CancelledError:
            await ctx.send('🛑 ポモドーロ停止！')
            await vc.disconnect()
            return

    task = asyncio.create_task(loop_task())
    GUILD_TIMER[ctx.guild.id] = task

@bot.command()
async def stop(ctx):
    task = GUILD_TIMER.get(ctx.guild.id)
    if task:
        task.cancel()
        del GUILD_TIMER[ctx.guild.id]
    else:
        await ctx.send('⏹️ タイマーは動いていません。')

bot.run(TOKEN)

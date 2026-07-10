import os
import asyncio
import discord

from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=",",
    intents=intents
)


@bot.event
async def on_ready():
    print(f"✅ Logado como {bot.user}")
    print(f"🆔 ID: {bot.user.id}")

    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} slash commands sincronizados.")
    except Exception as e:
        print(f"❌ Erro ao sincronizar comandos: {e}")


async def load_cogs():
    if not os.path.exists("cogs"):
        return

    for file in os.listdir("cogs"):
        if file.endswith(".py"):
            cog = f"cogs.{file[:-3]}"
            try:
                await bot.load_extension(cog)
                print(f"✅ Cog carregado: {cog}")
            except Exception as e:
                print(f"❌ Erro em {cog}: {e}")


async def main():
    async with bot:
        await load_cogs()
        await bot.start(TOKEN)


asyncio.run(main())

import os
import asyncio
import threading

import discord

from flask import Flask
from discord.ext import commands
from dotenv import load_dotenv


load_dotenv()

TOKEN = os.getenv("TOKEN", "")

print("=== DIAGNÓSTICO DO TOKEN ===")
print(f"Existe: {bool(TOKEN)}")
print(f"Tamanho: {len(TOKEN)}")
print(f"Pontos: {TOKEN.count('.')}")
print(f"Somente ASCII: {TOKEN.isascii()}")
print(f"Começa com aspas: {TOKEN.startswith(('\"', \"'\"))}")
print(f"Termina com aspas: {TOKEN.endswith(('\"', \"'\"))}")
print(f"Começa com 'Bot ': {TOKEN.startswith('Bot ')}")
print(f"Espaços/quebras nas pontas: {TOKEN != TOKEN.strip()}")
print("============================")

TOKEN = TOKEN.strip().strip('"').strip("'")

if TOKEN.startswith("Bot "):
    TOKEN = TOKEN[4:].strip()

if not TOKEN:
    raise RuntimeError("TOKEN vazio.")


# =========================
# SERVIDOR FLASK
# =========================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot online ✅", 200


@app.route("/status")
def status():
    return {
        "status": "online",
        "bot": str(bot.user) if bot.user else "iniciando"
    }, 200


def run_flask():
    port = int(os.getenv("PORT", 8080))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )


def start_flask():
    thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    thread.start()


# =========================
# BOT
# =========================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=",",
    intents=intents
)


@bot.event
async def on_ready():
    print("=" * 40)
    print(f"✅ Bot conectado como {bot.user}")
    print(f"🆔 ID: {bot.user.id}")
    print(f"🌐 Servidores: {len(bot.guilds)}")
    print(f"🏓 Ping: {round(bot.latency * 1000)}ms")
    print("=" * 40)

    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} comandos slash sincronizados.")

    except Exception as error:
        print(f"❌ Erro ao sincronizar comandos: {error}")


async def load_cogs():
    cogs_folder = "cogs"

    if not os.path.exists(cogs_folder):
        os.makedirs(cogs_folder)
        print("📁 Pasta cogs criada.")
        return

    for filename in os.listdir(cogs_folder):
        if not filename.endswith(".py"):
            continue

        if filename.startswith("_"):
            continue

        extension = f"cogs.{filename[:-3]}"

        try:
            await bot.load_extension(extension)
            print(f"✅ Cog carregado: {extension}")

        except Exception as error:
            print(f"❌ Erro ao carregar {extension}: {error}")


async def main():
    start_flask()

    async with bot:
        await load_cogs()
        await bot.start(TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print("🛑 Bot desligado manualmente.")

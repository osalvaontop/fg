import os
import asyncio
import threading

import discord

from flask import Flask
from discord.ext import commands
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

TOKEN = os.getenv("TOKEN", "")

print("=== DIAGNÓSTICO DO TOKEN ===")
print("Existe:", bool(TOKEN))
print("Tamanho:", len(TOKEN))
print("Pontos:", TOKEN.count("."))
print("ASCII:", TOKEN.isascii())
print("Primeiro caractere:", repr(TOKEN[:1]))
print("Último caractere:", repr(TOKEN[-1:]))
print("Começa com 'Bot ':", TOKEN.startswith("Bot "))
print("Tem espaços nas pontas:", TOKEN != TOKEN.strip())
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
    from pathlib import Path


async def load_cogs():
    from pathlib import Path
import traceback


async def load_cogs():
    cogs_path = Path(__file__).resolve().parent / "cogs"

    print("=" * 35)
    print(f"📂 Pasta dos cogs: {cogs_path}")
    print(f"📂 A pasta existe? {cogs_path.exists()}")
    print(f"📂 É uma pasta? {cogs_path.is_dir()}")

    if not cogs_path.exists():
        print("❌ A pasta cogs não foi encontrada.")
        return

    all_files = list(cogs_path.iterdir())
    print(f"📄 Tudo encontrado na pasta: {[file.name for file in all_files]}")

    py_files = [
        file
        for file in all_files
        if file.is_file()
        and file.suffix.lower() == ".py"
        and file.name != "__init__.py"
    ]

    print(f"🐍 Cogs detectados: {[file.name for file in py_files]}")

    if not py_files:
        print("⚠️ Nenhum cog foi encontrado.")
        return

    loaded = 0

    for file in py_files:
        extension = f"cogs.{file.stem}"

        print(f"🔄 Tentando carregar: {extension}")

        try:
            await bot.load_extension(extension)
            loaded += 1
            print(f"✅ Cog carregado: {extension}")

        except Exception:
            print(f"❌ Erro ao carregar: {extension}")
            traceback.print_exc()

    print(f"📦 Resultado: {loaded}/{len(py_files)} cogs carregados.")
    print("=" * 35)

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

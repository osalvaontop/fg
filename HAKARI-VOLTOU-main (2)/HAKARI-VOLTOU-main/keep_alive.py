# keep_alive.py
from flask import Flask, render_template_string, jsonify
from threading import Thread
import time
import os

app = Flask(__name__)

start_time = time.time()
bot_instance = None


def format_uptime(seconds):
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{days}d {hours}h {minutes}min"


def get_ping():
    if bot_instance and bot_instance.latency is not None:
        return round(bot_instance.latency * 1000)
    return None


def get_gateway_status(ping):
    if ping is None:
        return "Indisponível", "gray"
    elif ping < 150:
        return "Rápida", "green"
    elif ping < 300:
        return "Estável", "yellow"
    return "Lenta", "red"


@app.route("/api/status")
def api_status():
    uptime = format_uptime(time.time() - start_time)
    ping = get_ping()
    status, css_class = get_gateway_status(ping)

    return jsonify({
        "uptime": uptime,
        "ping": ping if ping is not None else "Indisponível",
        "gateway_status": status,
        "gateway_class": css_class,
        "port": os.getenv("PORT", "5000")
    })


@app.route("/")
def home():
    html = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Status do Hakari</title>

  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">

  <style>
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }

    body {
      min-height: 100vh;
      background:
        radial-gradient(circle at top left, rgba(0, 255, 214, 0.18), transparent 30%),
        radial-gradient(circle at right, rgba(255, 196, 87, 0.10), transparent 28%),
        linear-gradient(135deg, #071119, #071016 55%, #11120d);
      color: #f5f5f0;
      font-family: "Inter", sans-serif;
      padding: 28px;
    }

    .page {
      max-width: 944px;
      margin: auto;
    }

    .top {
      display: grid;
      grid-template-columns: 1.55fr 1fr;
      gap: 20px;
      margin-bottom: 20px;
    }

    .hero, .panel, .main-card {
      background: rgba(8, 18, 25, 0.78);
      border: 1px solid rgba(148, 163, 184, 0.14);
      border-radius: 24px;
      box-shadow: 0 30px 80px rgba(0, 0, 0, 0.35);
      backdrop-filter: blur(16px);
    }

    .hero {
      padding: 36px 28px 30px;
    }

    .eyebrow {
      color: #4eead4;
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      margin-bottom: 20px;
    }

    h1 {
      font-size: clamp(4rem, 9vw, 5.2rem);
      line-height: 0.9;
      letter-spacing: -0.08em;
      margin-bottom: 24px;
    }

    .desc {
      color: #a8b8c7;
      line-height: 1.7;
      font-size: 0.93rem;
      max-width: 520px;
    }

    .features {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
      margin-top: 24px;
    }

    .feature, .status-box, .mini-card {
      background: rgba(255, 255, 255, 0.045);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 14px;
      padding: 16px 14px;
    }

    .feature strong {
      display: block;
      font-size: 0.9rem;
      margin-bottom: 8px;
    }

    .feature p, .panel p, .mini-card p {
      color: #a9bac9;
      font-size: 0.82rem;
      line-height: 1.55;
    }

    .panel {
      padding: 22px;
    }

    .status-box {
      color: #f5f5f0;
      margin: 16px 0;
      line-height: 1.45;
      font-size: 0.88rem;
    }

    .tabs {
      display: flex;
      gap: 10px;
      margin: 18px 0 22px;
    }

    .tab {
      border: 1px solid rgba(255, 255, 255, 0.12);
      background: rgba(255, 255, 255, 0.045);
      color: #f5f5f0;
      padding: 10px 16px;
      border-radius: 999px;
      font-weight: 700;
      cursor: pointer;
    }

    .tab.active {
      border-color: rgba(245, 197, 91, 0.7);
      background: rgba(245, 197, 91, 0.10);
    }

    .main-card {
      padding: 28px 22px 22px;
    }

    .main-head {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 30px;
      margin-bottom: 26px;
    }

    h2 {
      font-size: clamp(2.2rem, 5vw, 3rem);
      line-height: 0.95;
      letter-spacing: -0.06em;
      margin-top: 8px;
    }

    .status-area {
      display: grid;
      grid-template-columns: 1.25fr 0.75fr;
      gap: 16px;
    }

    .live-box {
      background: rgba(255, 255, 255, 0.045);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 18px;
      padding: 16px;
      min-height: 170px;
    }

    .live-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 14px;
    }

    .badge {
      color: #4eead4;
      background: rgba(45, 212, 191, 0.12);
      padding: 9px 13px;
      border-radius: 999px;
      font-size: 0.7rem;
      font-weight: 800;
      text-transform: uppercase;
    }

    .new {
      color: #fff;
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.12);
      padding: 10px 16px;
      border-radius: 999px;
      font-weight: 800;
    }

    .row {
      display: flex;
      justify-content: space-between;
      padding: 11px 0;
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
      color: #a9bac9;
      font-size: 0.9rem;
    }

    .value {
      color: #f5f5f0;
      font-weight: 700;
    }

    .green {
      color: #4eead4;
    }

    .red {
      color: #ff6b6b;
    }

    .footer {
      text-align: center;
      margin-top: 22px;
      color: #667788;
      font-size: 0.75rem;
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }

    @media (max-width: 760px) {
      .top, .main-head, .status-area {
        grid-template-columns: 1fr;
      }

      .features {
        grid-template-columns: 1fr;
      }

      h1 {
        font-size: 3.7rem;
      }
    }
  </style>
</head>

<body>
  <div class="page">
    <section class="top">
      <div class="hero">
        <div class="eyebrow">HAKARI BOT feito pelo Mattzadas | Sempre online para entreter o seu servidor. </div>
        <h1>HAKARI</h1>
        <p class="desc">
          O HAKARI é um bot do Discord criado pelo Matt em Python, com foco em moderação, utilidades, automação e entretenimento. Conhecido por ser o famoso bot do comando /tomate.
        </p>

        <div class="features">
          <div class="feature">
            <strong>Propósito</strong>
            <p>Seu propósito é ser um bot do Discord pra entreter e criar coisas que nenhum outro bot tem.</p>
          </div>

          <div class="feature">
            <strong>Status</strong>
            <p>Atualmente Online 24/7 por UptimeRobot + Render.</p>
          </div>

          <div class="feature">
            <strong>Desenvolvedor</strong>
            <p>Matt é um garoto de 15 anos, obcecado por criar bots igual ao HAKARI. Sempre inteligente pra criar novas funcionalidades e paciente caso o erro 429(Rate Limit) venha novamente.</p>
          </div>
        </div>
      </div>

      <aside class="panel">
        <div class="eyebrow">Mais sobre o HAKARI</div>

        <div class="status-box" id="statusMessage">
          Mantido com atualizações constantes e otimizado para alta disponibilidade, o Hakari foi projetado para facilitar a administração de servidores enquanto oferece uma experiência moderna e intuitiva para administradores e membros. Mais do que um simples bot, ele é o resultado de dedicação, criatividade e centenas de horas de desenvolvimento contínuo.
        </div>
      </aside>
    </section>

    <main class="main-card">
      <div class="main-head">
        <div>
          <div class="eyebrow">Informações de Host</div>
          <h2>Saiba o que faz o HAKARI continuar vivo.</h2>
        </div>

        <p class="desc">
          Essas informações as vezes dão erros e não conseguem obter a informação correta. Cuidado.
        </p>
      </div>

      <section class="status-area">
        <div class="live-box">
          <div class="live-top">
            <span class="badge">INFORMAÇÕES</span>
          </div>

          <div class="row">
            <span>Status</span>
            <span class="value green" id="status">Online 24/7</span>
          </div>

          <div class="row">
            <span>Uptime</span>
            <span class="value" id="uptime">Carregando...</span>
          </div>

          <div class="row">
            <span>Gateway Discord</span>
            <span class="value" id="gateway">Carregando...</span>
          </div>

          <div class="row">
            <span>Ping</span>
            <span class="value" id="ping">Carregando...</span>
          </div>

          <div class="row">
            <span>Porta</span>
            <span class="value" id="port">Carregando...</span>
          </div>
        </div>

        <div class="mini-card">
          <div class="eyebrow">Como usar</div>
          <h3>Pra que essa página?</h3>
          <p>
            A Página de Host do Hakari é um painel público que exibe informações em tempo real sobre a hospedagem e o funcionamento do bot. Nela é possível acompanhar dados como status, uptime, conexão com o Gateway do Discord, latência da API, porta utilizada e outros detalhes técnicos, sempre preservando informações confidenciais como tokens, chaves e credenciais. O objetivo é oferecer transparência sobre a disponibilidade do Hakari sem comprometer sua segurança.
          </p>
        </div>
      </section>

      <footer class="footer">
        Página de Status do Hakari • Um bot feito pelo Matt
      </footer>
    </main>
  </div>

  <script>
  async function updateStatus() {
    try {
      const response = await fetch("/api/status");

      if (!response.ok) {
        throw new Error("API não respondeu");
      }

      const data = await response.json();

      document.getElementById("uptime").textContent = data.uptime ?? "Indisponível";
      document.getElementById("ping").textContent = data.ping ? `${data.ping} ms` : "Indisponível";
      document.getElementById("port").textContent = data.port ?? "Indisponível";

      const gateway = document.getElementById("gateway");
      gateway.textContent = data.gateway_status ?? "Indisponível";
      gateway.className = "value " + (data.gateway_class ?? "green");

    } catch (error) {
      document.getElementById("uptime").textContent = "Indisponível";
      document.getElementById("ping").textContent = "Falha";
      document.getElementById("port").textContent = "Indisponível";

      const gateway = document.getElementById("gateway");
      gateway.textContent = "Erro de conexão";
      gateway.className = "value red";
    }
  }

  updateStatus();
  setInterval(updateStatus, 5000);
</script>
</body>
</html>
"""

    return render_template_string(html)


def run():
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


def keep_alive(bot=None):
    global bot_instance
    bot_instance = bot

    server = Thread(target=run)
    server.daemon = True
    server.start()

import asyncio
import random
import sqlite3
import time
from pathlib import Path
from datetime import datetime, timedelta
from enum import Enum

import discord
from discord import app_commands
from discord.ext import commands


# ============================================================
# configurações
# ============================================================

ECONOMY_GUILD_ID = 1500231901397516340

DAILY_BONUS_ROLE_IDS = {
    1502738752106270831,
    1524830563003793429,
}

MIN_TRANSACTION = 1
MAX_TRANSACTION = 500_000_000_000_000
DAILY_COOLDOWN_SECONDS = 24 * 60 * 60

DATABASE_PATH = Path("data") / "economia.db"

# Configurações de empregos
WORK_COOLDOWN_SECONDS = 15 * 60  # 15 minutos
FAILED_INTERVIEW_COOLDOWN_SECONDS = 24 * 60 * 60  # 24 horas
MONTHLY_CYCLE_SECONDS = 30 * 24 * 60 * 60  # 30 dias

# Dados dos empregos
class JobData(Enum):
    # (nome, salário mensal, chance de aprovação, meta mensal)
    ESTAGIARIO = ("Estagiário", 800, 0.90, 40)
    ENTREGADOR = ("Entregador", 1200, 0.80, 50)
    FAXINEIRO = ("Faxineiro", 1500, 0.80, 60)
    GARCOM = ("Garçom", 1800, 0.60, 70)
    ATENDENTE = ("Atendente", 2200, 0.50, 70)
    MOTORISTA = ("Motorista", 2800, 0.45, 70)
    MECANICO = ("Mecânico", 3500, 0.45, 70)
    PROGRAMADOR_JUNIOR = ("Programador Júnior", 4500, 0.45, 70)
    POLICIAL = ("Policial", 5000, 0.30, 80)
    BOMBEIRO = ("Bombeiro", 5500, 0.30, 80)
    ENFERMEIRO = ("Enfermeiro", 6000, 0.30, 80)
    PROFESSOR = ("Professor", 6500, 0.25, 95)
    DESENVOLVEDOR = ("Desenvolvedor", 8000, 0.15, 100)
    ADVOGADO = ("Advogado", 9000, 0.10, 150)
    MEDICO = ("Médico", 12000, 0.10, 150)
    EMPRESARIO = ("Empresário", 18000, 0.10, 150)
    CEO = ("CEO", 30000, 0.10, 150)

    def get_name(self):
        return self.value[0]

    def get_salary(self):
        return self.value[1]

    def get_approval_chance(self):
        return self.value[2]

    def get_monthly_goal(self):
        return self.value[3]


class JobStatus(Enum):
    ATIVO = "ativo"
    AFASTADO = "afastado"
    DEMITIDO = "demitido"


# ============================================================
# banco de dados
# ============================================================

class EconomyDatabase:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.lock = asyncio.Lock()

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._create_tables()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=30,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def _create_tables(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL;")
            connection.execute("PRAGMA foreign_keys=ON;")

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS economy (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
                    last_daily INTEGER,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    job_name TEXT NOT NULL,
                    salary INTEGER NOT NULL,
                    monthly_goal INTEGER NOT NULL,
                    work_count INTEGER NOT NULL DEFAULT 0,
                    hire_date INTEGER NOT NULL,
                    cycle_start_date INTEGER NOT NULL,
                    next_payment_date INTEGER NOT NULL,
                    last_work_date INTEGER,
                    robbery_count INTEGER NOT NULL DEFAULT 0,
                    suspension_end_date INTEGER,
                    status TEXT NOT NULL DEFAULT 'ativo',
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )

    @staticmethod
    def _ensure_account(
        connection: sqlite3.Connection,
        guild_id: int,
        user_id: int,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO economy (guild_id, user_id, balance, last_daily)
            VALUES (?, ?, 0, NULL)
            """,
            (guild_id, user_id),
        )

    async def get_balance(self, guild_id: int, user_id: int) -> int:
        async with self.lock:
            with self._connect() as connection:
                self._ensure_account(connection, guild_id, user_id)

                row = connection.execute(
                    """
                    SELECT balance
                    FROM economy
                    WHERE guild_id = ? AND user_id = ?
                    """,
                    (guild_id, user_id),
                ).fetchone()

                return int(row["balance"])

    async def add_money(
        self,
        guild_id: int,
        user_id: int,
        amount: int,
    ) -> int:
        async with self.lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")

                try:
                    self._ensure_account(connection, guild_id, user_id)

                    connection.execute(
                        """
                        UPDATE economy
                        SET balance = balance + ?
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (amount, guild_id, user_id),
                    )

                    row = connection.execute(
                        """
                        SELECT balance
                        FROM economy
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (guild_id, user_id),
                    ).fetchone()

                    connection.execute("COMMIT")
                    return int(row["balance"])

                except Exception:
                    connection.execute("ROLLBACK")
                    raise

    async def remove_money(
        self,
        guild_id: int,
        user_id: int,
        amount: int,
    ) -> tuple[bool, int]:
        async with self.lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")

                try:
                    self._ensure_account(connection, guild_id, user_id)

                    row = connection.execute(
                        """
                        SELECT balance
                        FROM economy
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (guild_id, user_id),
                    ).fetchone()

                    current_balance = int(row["balance"])

                    if current_balance < amount:
                        connection.execute("ROLLBACK")
                        return False, current_balance

                    new_balance = current_balance - amount

                    connection.execute(
                        """
                        UPDATE economy
                        SET balance = ?
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (new_balance, guild_id, user_id),
                    )

                    connection.execute("COMMIT")
                    return True, new_balance

                except Exception:
                    connection.execute("ROLLBACK")
                    raise

    async def claim_daily(
        self,
        guild_id: int,
        user_id: int,
        amount: int,
    ) -> tuple[bool, int, int]:
        """
        retorna:
        - resgatado: bool
        - saldo ou segundos restantes: int
        - próximo timestamp: int
        """
        now = int(time.time())

        async with self.lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")

                try:
                    self._ensure_account(connection, guild_id, user_id)

                    row = connection.execute(
                        """
                        SELECT balance, last_daily
                        FROM economy
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (guild_id, user_id),
                    ).fetchone()

                    last_daily = row["last_daily"]

                    if last_daily is not None:
                        next_daily = int(last_daily) + DAILY_COOLDOWN_SECONDS

                        if now < next_daily:
                            remaining = next_daily - now
                            connection.execute("ROLLBACK")
                            return False, remaining, next_daily

                    new_balance = int(row["balance"]) + amount
                    next_daily = now + DAILY_COOLDOWN_SECONDS

                    connection.execute(
                        """
                        UPDATE economy
                        SET balance = ?, last_daily = ?
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (new_balance, now, guild_id, user_id),
                    )

                    connection.execute("COMMIT")
                    return True, new_balance, next_daily

                except Exception:
                    connection.execute("ROLLBACK")
                    raise

    async def transfer_money(
        self,
        guild_id: int,
        sender_id: int,
        receiver_id: int,
        amount: int,
    ) -> tuple[bool, int, int]:
        """
        retorna:
        - transferido: bool
        - saldo do remetente
        - saldo do destinatário
        """
        async with self.lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")

                try:
                    self._ensure_account(connection, guild_id, sender_id)
                    self._ensure_account(connection, guild_id, receiver_id)

                    sender_row = connection.execute(
                        """
                        SELECT balance
                        FROM economy
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (guild_id, sender_id),
                    ).fetchone()

                    receiver_row = connection.execute(
                        """
                        SELECT balance
                        FROM economy
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (guild_id, receiver_id),
                    ).fetchone()

                    sender_balance = int(sender_row["balance"])
                    receiver_balance = int(receiver_row["balance"])

                    if sender_balance < amount:
                        connection.execute("ROLLBACK")
                        return False, sender_balance, receiver_balance

                    new_sender_balance = sender_balance - amount
                    new_receiver_balance = receiver_balance + amount

                    connection.execute(
                        """
                        UPDATE economy
                        SET balance = ?
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (new_sender_balance, guild_id, sender_id),
                    )

                    connection.execute(
                        """
                        UPDATE economy
                        SET balance = ?
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (new_receiver_balance, guild_id, receiver_id),
                    )

                    connection.execute("COMMIT")
                    return True, new_sender_balance, new_receiver_balance

                except Exception:
                    connection.execute("ROLLBACK")
                    raise

    # ======================== JOBS METHODS ========================

    async def get_job(self, guild_id: int, user_id: int) -> dict | None:
        """Retorna as informações do emprego do usuário"""
        async with self.lock:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM jobs
                    WHERE guild_id = ? AND user_id = ?
                    """,
                    (guild_id, user_id),
                ).fetchone()

                return dict(row) if row else None

    async def hire_employee(
        self,
        guild_id: int,
        user_id: int,
        job_data: JobData,
    ) -> bool:
        """Contrata um usuário para um emprego"""
        now = int(time.time())
        next_payment = now + MONTHLY_CYCLE_SECONDS

        async with self.lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")

                try:
                    # Verifica se o usuário já possui um emprego
                    existing_job = connection.execute(
                        """
                        SELECT job_name FROM jobs
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (guild_id, user_id),
                    ).fetchone()

                    if existing_job is not None:
                        connection.execute("ROLLBACK")
                        return False

                    connection.execute(
                        """
                        INSERT INTO jobs (
                            guild_id, user_id, job_name, salary, monthly_goal,
                            hire_date, cycle_start_date, next_payment_date, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            guild_id,
                            user_id,
                            job_data.get_name(),
                            job_data.get_salary(),
                            job_data.get_monthly_goal(),
                            now,
                            now,
                            next_payment,
                            JobStatus.ATIVO.value,
                        ),
                    )

                    connection.execute("COMMIT")
                    return True

                except Exception:
                    connection.execute("ROLLBACK")
                    raise

    async def work(self, guild_id: int, user_id: int) -> tuple[bool, str]:
        """Registra um trabalho para o usuário"""
        now = int(time.time())

        async with self.lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")

                try:
                    job = connection.execute(
                        """
                        SELECT * FROM jobs
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (guild_id, user_id),
                    ).fetchone()

                    if job is None:
                        connection.execute("ROLLBACK")
                        return False, "você não possui um emprego. use `/entrevista` para participar de uma."

                    # Verifica se está afastado
                    if job["status"] == JobStatus.AFASTADO.value:
                        if job["suspension_end_date"] and now < job["suspension_end_date"]:
                            connection.execute("ROLLBACK")
                            return False, f"você está afastado até <t:{job['suspension_end_date']}:f>."

                        # Remove o afastamento
                        connection.execute(
                            """
                            UPDATE jobs
                            SET status = ?, suspension_end_date = NULL
                            WHERE guild_id = ? AND user_id = ?
                            """,
                            (JobStatus.ATIVO.value, guild_id, user_id),
                        )

                    # Verifica cooldown de 15 minutos
                    if job["last_work_date"] is not None:
                        next_work_time = job["last_work_date"] + WORK_COOLDOWN_SECONDS
                        if now < next_work_time:
                            connection.execute("ROLLBACK")
                            return False, f"você poderá trabalhar novamente em <t:{next_work_time}:R>."

                    # Verifica se atingiu a meta mensal
                    if job["work_count"] >= job["monthly_goal"]:
                        connection.execute("ROLLBACK")
                        return False, f"você já atingiu a meta mensal de {job['monthly_goal']} trabalhos."

                    # Atualiza o progresso
                    new_work_count = job["work_count"] + 1

                    connection.execute(
                        """
                        UPDATE jobs
                        SET work_count = ?, last_work_date = ?
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (new_work_count, now, guild_id, user_id),
                    )

                    connection.execute("COMMIT")
                    return True, f"você trabalhou com sucesso! progresso: {new_work_count}/{job['monthly_goal']}"

                except Exception:
                    connection.execute("ROLLBACK")
                    raise

    async def pay_salary(self, guild_id: int, user_id: int) -> tuple[bool, int]:
        """Processa o pagamento mensal e retorna o novo saldo"""
        now = int(time.time())
        next_payment = now + MONTHLY_CYCLE_SECONDS

        async with self.lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")

                try:
                    job = connection.execute(
                        """
                        SELECT * FROM jobs
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (guild_id, user_id),
                    ).fetchone()

                    if job is None:
                        connection.execute("ROLLBACK")
                        return False, 0

                    # Calcula o salário
                    if job["work_count"] >= job["monthly_goal"]:
                        salary_earned = job["salary"]
                    else:
                        salary_earned = int(job["salary"] * job["work_count"] / job["monthly_goal"])

                    # Adiciona o dinheiro
                    self._ensure_account(connection, guild_id, user_id)
                    connection.execute(
                        """
                        UPDATE economy
                        SET balance = balance + ?
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (salary_earned, guild_id, user_id),
                    )

                    # Obtém o novo saldo após o pagamento
                    balance_row = connection.execute(
                        """
                        SELECT balance
                        FROM economy
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (guild_id, user_id),
                    ).fetchone()

                    new_balance = int(balance_row["balance"])

                    # Reseta o ciclo mensal
                    connection.execute(
                        """
                        UPDATE jobs
                        SET work_count = 0, cycle_start_date = ?, next_payment_date = ?
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (now, next_payment, guild_id, user_id),
                    )

                    connection.execute("COMMIT")
                    return True, new_balance

                except Exception:
                    connection.execute("ROLLBACK")
                    raise

    async def add_suspension(self, guild_id: int, user_id: int) -> tuple[bool, int]:
        """Adiciona uma suspensão progressiva ao usuário"""
        async with self.lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")

                try:
                    job = connection.execute(
                        """
                        SELECT * FROM jobs
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (guild_id, user_id),
                    ).fetchone()

                    if job is None:
                        connection.execute("ROLLBACK")
                        return False, 0

                    now = int(time.time())
                    robbery_count = job["robbery_count"] + 1

                    # Tabela de punições
                    suspension_days = {
                        1: 5,
                        2: 10,
                        3: 15,
                        4: 20,
                        5: 25,
                        6: 30,
                        7: None,  # Demissão
                    }

                    if robbery_count == 7:
                        # Demissão
                        connection.execute(
                            """
                            UPDATE jobs
                            SET status = ?, robbery_count = ?
                            WHERE guild_id = ? AND user_id = ?
                            """,
                            (JobStatus.DEMITIDO.value, robbery_count, guild_id, user_id),
                        )
                        connection.execute("COMMIT")
                        return True, 0

                    # Suspensão
                    days = suspension_days.get(robbery_count, 30)
                    suspension_end = now + (days * 24 * 60 * 60)

                    connection.execute(
                        """
                        UPDATE jobs
                        SET status = ?, suspension_end_date = ?, robbery_count = ?
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (JobStatus.AFASTADO.value, suspension_end, robbery_count, guild_id, user_id),
                    )

                    connection.execute("COMMIT")
                    return True, suspension_end

                except Exception:
                    connection.execute("ROLLBACK")
                    raise

    async def fire_employee(self, guild_id: int, user_id: int) -> bool:
        """Remove o emprego do usuário"""
        async with self.lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")

                try:
                    connection.execute(
                        """
                        DELETE FROM jobs
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (guild_id, user_id),
                    )

                    connection.execute("COMMIT")
                    return True

                except Exception:
                    connection.execute("ROLLBACK")
                    raise


# ============================================================
# confirmação do pix
# ============================================================

class PixConfirmationView(discord.ui.View):
    def __init__(
        self,
        *,
        database: EconomyDatabase,
        guild_id: int,
        sender: discord.Member,
        receiver: discord.Member,
        amount: int,
    ):
        super().__init__(timeout=120)

        self.database = database
        self.guild_id = guild_id
        self.sender = sender
        self.receiver = receiver
        self.amount = amount

        self.finished = False
        self.message: discord.InteractionMessage | None = None

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.receiver.id:
            await interaction.response.send_message(
                "apenas quem vai receber o pix pode confirmar ou recusar.",
                ephemeral=True,
            )
            return False

        return True

    def disable_all_buttons(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    @discord.ui.button(
        label="confirmar pix",
        style=discord.ButtonStyle.green,
        emoji="✅",
    )
    async def confirm_pix(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self.finished:
            await interaction.response.send_message(
                "este pix já foi finalizado.",
                ephemeral=True,
            )
            return

        self.finished = True
        self.disable_all_buttons()

        success, sender_balance, receiver_balance = (
            await self.database.transfer_money(
                guild_id=self.guild_id,
                sender_id=self.sender.id,
                receiver_id=self.receiver.id,
                amount=self.amount,
            )
        )

        if not success:
            embed = discord.Embed(
                title="pix cancelado",
                description=(
                    f"{self.sender.mention} não possui mais saldo suficiente "
                    "para concluir esta transferência."
                ),
                color=discord.Color.red(),
            )
            embed.add_field(
                name="saldo atual",
                value=f"R$ {sender_balance:,}".replace(",", "."),
                inline=False,
            )

            await interaction.response.edit_message(
                embed=embed,
                view=self,
            )
            self.stop()
            return

        embed = discord.Embed(
            title="pix realizado com sucesso",
            description=(
                f"{self.sender.mention} enviou "
                f"**R$ {self.amount:,}** para {self.receiver.mention}."
            ).replace(",", "."),
            color=discord.Color.green(),
        )
        embed.add_field(
            name=f"saldo de {self.sender.display_name}",
            value=f"R$ {sender_balance:,}".replace(",", "."),
        )
        embed.add_field(
            name=f"saldo de {self.receiver.display_name}",
            value=f"R$ {receiver_balance:,}".replace(",", "."),
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self,
        )
        self.stop()

    @discord.ui.button(
        label="recusar",
        style=discord.ButtonStyle.red,
        emoji="❌",
    )
    async def refuse_pix(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self.finished:
            await interaction.response.send_message(
                "este pix já foi finalizado.",
                ephemeral=True,
            )
            return

        self.finished = True
        self.disable_all_buttons()

        embed = discord.Embed(
            title="pix recusado",
            description=(
                f"{self.receiver.mention} recusou o pix de "
                f"**R$ {self.amount:,}** enviado por {self.sender.mention}."
            ).replace(",", "."),
            color=discord.Color.red(),
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self,
        )
        self.stop()

    async def on_timeout(self) -> None:
        if self.finished:
            return

        self.finished = True
        self.disable_all_buttons()

        if self.message is None:
            return

        embed = discord.Embed(
            title="pix expirado",
            description=(
                "a confirmação não foi respondida dentro de 2 minutos. "
                "nenhum valor foi transferido."
            ),
            color=discord.Color.red(),
        )

        try:
            await self.message.edit(embed=embed, view=self)
        except discord.HTTPException:
            pass


# ============================================================
# seleção de profissões
# ============================================================

class JobSelectView(discord.ui.View):
    def __init__(self, database: EconomyDatabase, guild_id: int, user_id: int):
        super().__init__(timeout=60)
        self.database = database
        self.guild_id = guild_id
        self.user_id = user_id
        self.selected_job: JobData | None = None

    @discord.ui.select(
        placeholder="selecione uma profissão",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label=job.get_name(), value=job.name)
            for job in JobData
        ],
    )
    async def select_job(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select,
    ) -> None:
        job_name = select.values[0]
        self.selected_job = JobData[job_name]

        success = await self.database.hire_employee(
            guild_id=self.guild_id,
            user_id=self.user_id,
            job_data=self.selected_job,
        )

        if not success:
            await interaction.response.send_message(
                "você já possui um emprego! use `/demitir` para sair do atual.",
                ephemeral=True,
            )
            return

        # Simula a entrevista
        approval_chance = self.selected_job.get_approval_chance()
        interview_result = random.random() < approval_chance

        if interview_result:
            embed = discord.Embed(
                title="parabéns! você foi aprovado!",
                description=f"você é agora um(a) **{self.selected_job.get_name()}**.",
                color=discord.Color.green(),
            )
            embed.add_field(
                name="salário mensal",
                value=f"R$ {self.selected_job.get_salary():,}".replace(",", "."),
                inline=True,
            )
            embed.add_field(
                name="meta mensal",
                value=f"{self.selected_job.get_monthly_goal()} trabalhos",
                inline=True,
            )
            embed.add_field(
                name="próximo passo",
                value="use `/trabalhar` para começar a ganhar dinheiro!",
                inline=False,
            )

            await interaction.response.send_message(embed=embed)
        else:
            # Remove o emprego
            await self.database.fire_employee(self.guild_id, self.user_id)

            embed = discord.Embed(
                title="reprovado na entrevista!",
                description=f"você não foi aprovado para a posição de **{self.selected_job.get_name()}**.",
                color=discord.Color.red(),
            )
            embed.add_field(
                name="chance de aprovação",
                value=f"{approval_chance * 100:.0f}%",
                inline=False,
            )
            embed.add_field(
                name="próxima tentativa",
                value="você pode tentar novamente em 24 horas.",
                inline=False,
            )

            await interaction.response.send_message(embed=embed)

        self.stop()


# ============================================================
# cog
# ============================================================

class Economia(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.database = EconomyDatabase(DATABASE_PATH)

    @staticmethod
    def is_guild_owner(interaction: discord.Interaction) -> bool:
        return (
            interaction.guild is not None
            and interaction.guild.owner_id == interaction.user.id
        )

    @app_commands.command(
        name="saldo",
        description="mostra o saldo atual do usuário ou de outra pessoa.",
    )
    @app_commands.guilds(discord.Object(id=ECONOMY_GUILD_ID))
    @app_commands.describe(
        usuario="usuário para verificar o saldo (opcional, padrão é você).",
    )
    async def saldo(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member | None = None,
    ) -> None:
        target_user = usuario if usuario is not None else interaction.user

        if not isinstance(target_user, discord.Member):
            await interaction.response.send_message(
                "não foi possível obter informações do usuário.",
                ephemeral=True,
            )
            return

        balance = await self.database.get_balance(
            guild_id=interaction.guild_id,
            user_id=target_user.id,
        )

        if usuario is None:
            embed = discord.Embed(
                title="seu saldo",
                description=f"R$ {balance:,}".replace(",", "."),
                color=discord.Color.green(),
            )
            embed.set_thumbnail(url=interaction.user.avatar.url if interaction.user.avatar else "")
        else:
            embed = discord.Embed(
                title=f"saldo de {target_user.display_name}",
                description=f"R$ {balance:,}".replace(",", "."),
                color=discord.Color.blurple(),
            )
            embed.set_thumbnail(url=target_user.avatar.url if target_user.avatar else "")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="addreais",
        description="adiciona reais ao saldo de um usuário.",
    )
    @app_commands.guilds(discord.Object(id=ECONOMY_GUILD_ID))
    @app_commands.describe(
        usuario="usuário que receberá os reais.",
        quantia="quantidade entre 1 e 500.000.000.000.000 reais.",
    )
    async def addreais(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        quantia: app_commands.Range[int, MIN_TRANSACTION, MAX_TRANSACTION],
    ) -> None:
        if not self.is_guild_owner(interaction):
            await interaction.response.send_message(
                "apenas o dono com posse do servidor pode usar este comando.",
                ephemeral=True,
            )
            return

        new_balance = await self.database.add_money(
            guild_id=interaction.guild_id,
            user_id=usuario.id,
            amount=quantia,
        )

        await interaction.response.send_message(
            (
                f"adicionei **R$ {quantia:,}** para {usuario.mention}.\n"
                f"novo saldo: **R$ {new_balance:,}**."
            ).replace(",", "."),
        )

    @app_commands.command(
        name="daily",
        description="resgata uma recompensa diária em reais.",
    )
    @app_commands.guilds(discord.Object(id=ECONOMY_GUILD_ID))
    async def daily(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            return

        base_amount = random.randint(100, 300)

        has_bonus_role = any(
            role.id in DAILY_BONUS_ROLE_IDS
            for role in interaction.user.roles
        )

        amount = int(base_amount * 1.5) if has_bonus_role else base_amount

        claimed, value, next_daily = await self.database.claim_daily(
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            amount=amount,
        )

        if not claimed:
            await interaction.response.send_message(
                (
                    "você já resgatou seu daily.\n"
                    f"tente novamente <t:{next_daily}:R>."
                ),
            )
            return

        bonus_text = (
            "\nbônus de cargo **1,5x** aplicado."
            if has_bonus_role
            else ""
        )

        await interaction.response.send_message(
            (
                f"você recebeu **R$ {amount:,}** no daily."
                f"{bonus_text}\n"
                f"seu saldo agora é **R$ {value:,}**.\n"
                f"próximo daily: <t:{next_daily}:R>."
            ).replace(",", "."),
        )

    @app_commands.command(
        name="pix",
        description="envia reais para outro usuário após a confirmação dele.",
    )
    @app_commands.guilds(discord.Object(id=ECONOMY_GUILD_ID))
    @app_commands.describe(
        usuario="usuário que receberá o pix.",
        quantia="quantidade entre 3 e 500.000.000.000.000 reais.",
    )
    async def pix(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        quantia: app_commands.Range[int, MIN_TRANSACTION, MAX_TRANSACTION],
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            return

        if usuario.id == interaction.user.id:
            await interaction.response.send_message(
                "você não pode enviar um pix para si mesmo.",
                ephemeral=True,
            )
            return

        if usuario.bot:
            await interaction.response.send_message(
                "você não pode enviar um pix para bots.",
                ephemeral=True,
            )
            return

        sender_balance = await self.database.get_balance(
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
        )

        if sender_balance < quantia:
            await interaction.response.send_message(
                (
                    f"saldo insuficiente. você possui **R$ {sender_balance:,}**."
                ).replace(",", "."),
                ephemeral=True,
            )
            return

        view = PixConfirmationView(
            database=self.database,
            guild_id=interaction.guild_id,
            sender=interaction.user,
            receiver=usuario,
            amount=quantia,
        )

        embed = discord.Embed(
            title="confirmação de pix",
            description=(
                f"{usuario.mention}, {interaction.user.mention} quer enviar "
                f"**R$ {quantia:,}** para você.\n\n"
                "confirme ou recuse usando os botões abaixo."
            ).replace(",", "."),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="a solicitação expira em 2 minutos.")

        await interaction.response.send_message(
            content=usuario.mention,
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )

        view.message = await interaction.original_response()

    @app_commands.command(
        name="remover_reais",
        description="remove reais do saldo de um usuário.",
    )
    @app_commands.guilds(discord.Object(id=ECONOMY_GUILD_ID))
    @app_commands.describe(
        usuario="usuário que terá reais removidos.",
        quantia="quantidade de reais que será removida.",
    )
    async def remover_reais(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        quantia: app_commands.Range[int, 1, MAX_TRANSACTION],
    ) -> None:
        if not self.is_guild_owner(interaction):
            await interaction.response.send_message(
                "apenas o dono com posse do servidor pode usar este comando.",
                ephemeral=True,
            )
            return

        success, new_balance = await self.database.remove_money(
            guild_id=interaction.guild_id,
            user_id=usuario.id,
            amount=quantia,
        )

        if not success:
            await interaction.response.send_message(
                (
                    f"{usuario.mention} não possui **R$ {quantia:,}**.\n"
                    f"saldo atual: **R$ {new_balance:,}**."
                ).replace(",", "."),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            (
                f"removi **R$ {quantia:,}** de {usuario.mention}.\n"
                f"novo saldo: **R$ {new_balance:,}**."
            ).replace(",", "."),
            ephemeral=False,
        )

    # ======================== JOBS COMMANDS ========================

    @app_commands.command(
        name="entrevista",
        description="participe de uma entrevista de emprego.",
    )
    @app_commands.guilds(discord.Object(id=ECONOMY_GUILD_ID))
    async def entrevista(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Abre o seletor de profissões para a entrevista"""
        job = await self.database.get_job(interaction.guild_id, interaction.user.id)

        if job is not None:
            await interaction.response.send_message(
                "você já possui um emprego! use `/demitir` para sair do atual.",
                ephemeral=True,
            )
            return

        view = JobSelectView(
            database=self.database,
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
        )

        embed = discord.Embed(
            title="entrevista de emprego",
            description="escolha uma profissão para participar da entrevista.",
            color=discord.Color.blurple(),
        )

        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(
        name="trabalhar",
        description="trabalhe para ganhar dinheiro.",
    )
    @app_commands.guilds(discord.Object(id=ECONOMY_GUILD_ID))
    async def trabalhar(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Registra um trabalho para o usuário"""
        success, message = await self.database.work(interaction.guild_id, interaction.user.id)

        if success:
            await interaction.response.send_message(message)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(
        name="emprego",
        description="mostra informações sobre seu emprego atual.",
    )
    @app_commands.guilds(discord.Object(id=ECONOMY_GUILD_ID))
    async def emprego(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Mostra informações do emprego"""
        job = await self.database.get_job(interaction.guild_id, interaction.user.id)

        if job is None:
            await interaction.response.send_message(
                "você não possui um emprego. use `/entrevista` para participar de uma.",
                ephemeral=True,
            )
            return

        status_emoji = {
            JobStatus.ATIVO.value: "✅",
            JobStatus.AFASTADO.value: "⏸️",
            JobStatus.DEMITIDO.value: "❌",
        }

        embed = discord.Embed(
            title=f"informações de emprego",
            description=f"{status_emoji.get(job['status'], '❓')} {job['job_name']}",
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="salário mensal",
            value=f"R$ {job['salary']:,}".replace(",", "."),
            inline=True,
        )

        embed.add_field(
            name="meta mensal",
            value=f"{job['work_count']}/{job['monthly_goal']} trabalhos",
            inline=True,
        )

        embed.add_field(
            name="contratado em",
            value=f"<t:{job['hire_date']}:d>",
            inline=True,
        )

        embed.add_field(
            name="próximo pagamento",
            value=f"<t:{job['next_payment_date']}:R>",
            inline=True,
        )

        if job["status"] == JobStatus.AFASTADO.value and job["suspension_end_date"]:
            embed.add_field(
                name="volta ao trabalho",
                value=f"<t:{job['suspension_end_date']}:f>",
                inline=True,
            )

        embed.add_field(
            name="infrações",
            value=f"{job['robbery_count']}/7",
            inline=True,
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="demitir",
        description="saia do seu emprego atual.",
    )
    @app_commands.guilds(discord.Object(id=ECONOMY_GUILD_ID))
    async def demitir(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Demite o usuário do emprego"""
        success = await self.database.fire_employee(interaction.guild_id, interaction.user.id)

        if not success:
            await interaction.response.send_message(
                "você não possui um emprego.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message("você saiu do seu emprego.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Economia(bot))

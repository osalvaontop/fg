import asyncio
import random
import sqlite3
import time
from enum import Enum
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks


# ============================================================
# CONFIGURAÇÕES
# ============================================================

ECONOMY_GUILD_ID = 1500231901397516340

DAILY_BONUS_ROLE_IDS = {
    1502738752106270831,
    1524830563003793429,
}

MIN_TRANSACTION = 1
MIN_PIX = 3
MAX_TRANSACTION = 500_000_000_000_000

DAILY_COOLDOWN_SECONDS = 24 * 60 * 60
WORK_COOLDOWN_SECONDS = 15 * 60
FAILED_INTERVIEW_COOLDOWN_SECONDS = 24 * 60 * 60
MONTHLY_CYCLE_SECONDS = 30 * 24 * 60 * 60

DATABASE_PATH = Path("data") / "economia.db"


# ============================================================
# EMPREGOS
# ============================================================

class JobData(Enum):
    # nome, salário, chance de aprovação, meta mensal
    ESTAGIARIO = ("Estagiário", 800, 0.90, 40)
    ENTREGADOR = ("Entregador", 1_200, 0.80, 50)
    FAXINEIRO = ("Faxineiro", 1_500, 0.80, 60)
    GARCOM = ("Garçom", 1_800, 0.60, 70)
    ATENDENTE = ("Atendente", 2_200, 0.50, 70)
    MOTORISTA = ("Motorista", 2_800, 0.45, 70)
    MECANICO = ("Mecânico", 3_500, 0.45, 70)
    PROGRAMADOR_JUNIOR = ("Programador Júnior", 4_500, 0.45, 70)
    POLICIAL = ("Policial", 5_000, 0.30, 80)
    BOMBEIRO = ("Bombeiro", 5_500, 0.30, 80)
    ENFERMEIRO = ("Enfermeiro", 6_000, 0.30, 80)
    PROFESSOR = ("Professor", 6_500, 0.25, 95)
    DESENVOLVEDOR = ("Desenvolvedor", 8_000, 0.15, 100)
    ADVOGADO = ("Advogado", 9_000, 0.10, 150)
    MEDICO = ("Médico", 12_000, 0.10, 150)
    EMPRESARIO = ("Empresário", 18_000, 0.10, 150)
    CEO = ("CEO", 30_000, 0.10, 150)

    @property
    def display_name(self) -> str:
        return self.value[0]

    @property
    def salary(self) -> int:
        return self.value[1]

    @property
    def approval_chance(self) -> float:
        return self.value[2]

    @property
    def monthly_goal(self) -> int:
        return self.value[3]


class JobStatus(Enum):
    ATIVO = "ativo"
    AFASTADO = "afastado"


def format_money(value: int) -> str:
    return f"R$ {value:,}".replace(",", ".")


# ============================================================
# BANCO DE DADOS
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
        """
        Cria as tabelas sem ativar WAL.

        O WAL pode causar travamentos ou comportamento estranho em alguns
        ambientes de hospedagem com sistema de arquivos efêmero.
        """
        with self._connect() as connection:
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

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS interview_cooldowns (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    next_interview INTEGER NOT NULL,
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
            INSERT OR IGNORE INTO economy (
                guild_id,
                user_id,
                balance,
                last_daily
            )
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
                            connection.execute("ROLLBACK")
                            return False, next_daily - now, next_daily

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

    # ========================================================
    # ENTREVISTAS
    # ========================================================

    async def get_interview_cooldown(
        self,
        guild_id: int,
        user_id: int,
    ) -> int | None:
        now = int(time.time())

        async with self.lock:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT next_interview
                    FROM interview_cooldowns
                    WHERE guild_id = ? AND user_id = ?
                    """,
                    (guild_id, user_id),
                ).fetchone()

                if row is None:
                    return None

                next_interview = int(row["next_interview"])

                if now >= next_interview:
                    connection.execute(
                        """
                        DELETE FROM interview_cooldowns
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (guild_id, user_id),
                    )
                    return None

                return next_interview

    async def set_failed_interview_cooldown(
        self,
        guild_id: int,
        user_id: int,
    ) -> int:
        next_interview = int(time.time()) + FAILED_INTERVIEW_COOLDOWN_SECONDS

        async with self.lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO interview_cooldowns (
                        guild_id,
                        user_id,
                        next_interview
                    )
                    VALUES (?, ?, ?)
                    ON CONFLICT(guild_id, user_id)
                    DO UPDATE SET next_interview = excluded.next_interview
                    """,
                    (guild_id, user_id, next_interview),
                )

        return next_interview

    async def clear_interview_cooldown(
        self,
        guild_id: int,
        user_id: int,
    ) -> None:
        async with self.lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    DELETE FROM interview_cooldowns
                    WHERE guild_id = ? AND user_id = ?
                    """,
                    (guild_id, user_id),
                )

    # ========================================================
    # EMPREGOS
    # ========================================================

    async def get_job(self, guild_id: int, user_id: int) -> dict | None:
        async with self.lock:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT *
                    FROM jobs
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
        now = int(time.time())
        next_payment = now + MONTHLY_CYCLE_SECONDS

        async with self.lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")

                try:
                    existing_job = connection.execute(
                        """
                        SELECT 1
                        FROM jobs
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
                            guild_id,
                            user_id,
                            job_name,
                            salary,
                            monthly_goal,
                            work_count,
                            hire_date,
                            cycle_start_date,
                            next_payment_date,
                            last_work_date,
                            robbery_count,
                            suspension_end_date,
                            status
                        )
                        VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, NULL, 0, NULL, ?)
                        """,
                        (
                            guild_id,
                            user_id,
                            job_data.display_name,
                            job_data.salary,
                            job_data.monthly_goal,
                            now,
                            now,
                            next_payment,
                            JobStatus.ATIVO.value,
                        ),
                    )

                    connection.execute(
                        """
                        DELETE FROM interview_cooldowns
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (guild_id, user_id),
                    )

                    connection.execute("COMMIT")
                    return True

                except Exception:
                    connection.execute("ROLLBACK")
                    raise

    async def work(
        self,
        guild_id: int,
        user_id: int,
    ) -> tuple[bool, str]:
        now = int(time.time())

        async with self.lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")

                try:
                    job = connection.execute(
                        """
                        SELECT *
                        FROM jobs
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (guild_id, user_id),
                    ).fetchone()

                    if job is None:
                        connection.execute("ROLLBACK")
                        return (
                            False,
                            "você não possui um emprego. use `/entrevista` para participar de uma.",
                        )

                    if job["status"] == JobStatus.AFASTADO.value:
                        suspension_end = job["suspension_end_date"]

                        if suspension_end and now < int(suspension_end):
                            connection.execute("ROLLBACK")
                            return (
                                False,
                                f"você está afastado até <t:{int(suspension_end)}:f>.",
                            )

                        connection.execute(
                            """
                            UPDATE jobs
                            SET status = ?, suspension_end_date = NULL
                            WHERE guild_id = ? AND user_id = ?
                            """,
                            (JobStatus.ATIVO.value, guild_id, user_id),
                        )

                    last_work_date = job["last_work_date"]

                    if last_work_date is not None:
                        next_work = int(last_work_date) + WORK_COOLDOWN_SECONDS

                        if now < next_work:
                            connection.execute("ROLLBACK")
                            return (
                                False,
                                f"você poderá trabalhar novamente <t:{next_work}:R>.",
                            )

                    work_count = int(job["work_count"])
                    monthly_goal = int(job["monthly_goal"])

                    if work_count >= monthly_goal:
                        connection.execute("ROLLBACK")
                        return (
                            False,
                            f"você já atingiu a meta mensal de {monthly_goal} trabalhos.",
                        )

                    new_work_count = work_count + 1

                    connection.execute(
                        """
                        UPDATE jobs
                        SET work_count = ?, last_work_date = ?
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (new_work_count, now, guild_id, user_id),
                    )

                    connection.execute("COMMIT")

                    return (
                        True,
                        (
                            "você trabalhou com sucesso!\n"
                            f"progresso mensal: **{new_work_count}/{monthly_goal}**"
                        ),
                    )

                except Exception:
                    connection.execute("ROLLBACK")
                    raise

    async def fire_employee(
        self,
        guild_id: int,
        user_id: int,
    ) -> bool:
        async with self.lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")

                try:
                    cursor = connection.execute(
                        """
                        DELETE FROM jobs
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (guild_id, user_id),
                    )

                    connection.execute("COMMIT")
                    return cursor.rowcount > 0

                except Exception:
                    connection.execute("ROLLBACK")
                    raise

    async def add_suspension(
        self,
        guild_id: int,
        user_id: int,
    ) -> tuple[bool, int | None, bool]:
        """
        Retorna:
        - sucesso
        - timestamp do fim da suspensão, ou None
        - se o usuário foi demitido
        """
        async with self.lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")

                try:
                    job = connection.execute(
                        """
                        SELECT robbery_count
                        FROM jobs
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (guild_id, user_id),
                    ).fetchone()

                    if job is None:
                        connection.execute("ROLLBACK")
                        return False, None, False

                    robbery_count = int(job["robbery_count"]) + 1

                    suspension_days = {
                        1: 5,
                        2: 10,
                        3: 15,
                        4: 20,
                        5: 25,
                        6: 30,
                    }

                    if robbery_count >= 7:
                        connection.execute(
                            """
                            DELETE FROM jobs
                            WHERE guild_id = ? AND user_id = ?
                            """,
                            (guild_id, user_id),
                        )

                        connection.execute("COMMIT")
                        return True, None, True

                    days = suspension_days[robbery_count]
                    suspension_end = int(time.time()) + days * 24 * 60 * 60

                    connection.execute(
                        """
                        UPDATE jobs
                        SET
                            status = ?,
                            suspension_end_date = ?,
                            robbery_count = ?
                        WHERE guild_id = ? AND user_id = ?
                        """,
                        (
                            JobStatus.AFASTADO.value,
                            suspension_end,
                            robbery_count,
                            guild_id,
                            user_id,
                        ),
                    )

                    connection.execute("COMMIT")
                    return True, suspension_end, False

                except Exception:
                    connection.execute("ROLLBACK")
                    raise

    async def process_due_salaries(self) -> list[dict]:
        """
        Processa todos os salários vencidos.

        O salário é proporcional ao número de trabalhos concluídos.
        Quem atingir a meta recebe o valor integral.
        """
        now = int(time.time())
        payments: list[dict] = []

        async with self.lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")

                try:
                    due_jobs = connection.execute(
                        """
                        SELECT *
                        FROM jobs
                        WHERE next_payment_date <= ?
                        """,
                        (now,),
                    ).fetchall()

                    for job in due_jobs:
                        guild_id = int(job["guild_id"])
                        user_id = int(job["user_id"])
                        salary = int(job["salary"])
                        work_count = int(job["work_count"])
                        monthly_goal = int(job["monthly_goal"])

                        if monthly_goal <= 0:
                            earned = 0
                        elif work_count >= monthly_goal:
                            earned = salary
                        else:
                            earned = int(salary * work_count / monthly_goal)

                        self._ensure_account(connection, guild_id, user_id)

                        if earned > 0:
                            connection.execute(
                                """
                                UPDATE economy
                                SET balance = balance + ?
                                WHERE guild_id = ? AND user_id = ?
                                """,
                                (earned, guild_id, user_id),
                            )

                        next_payment = now + MONTHLY_CYCLE_SECONDS

                        connection.execute(
                            """
                            UPDATE jobs
                            SET
                                work_count = 0,
                                cycle_start_date = ?,
                                next_payment_date = ?,
                                last_work_date = NULL
                            WHERE guild_id = ? AND user_id = ?
                            """,
                            (now, next_payment, guild_id, user_id),
                        )

                        payments.append(
                            {
                                "guild_id": guild_id,
                                "user_id": user_id,
                                "amount": earned,
                                "job_name": job["job_name"],
                                "next_payment": next_payment,
                            }
                        )

                    connection.execute("COMMIT")
                    return payments

                except Exception:
                    connection.execute("ROLLBACK")
                    raise


# ============================================================
# CONFIRMAÇÃO DO PIX
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
                value=format_money(sender_balance),
                inline=False,
            )

            await interaction.response.edit_message(embed=embed, view=self)
            self.stop()
            return

        embed = discord.Embed(
            title="pix realizado com sucesso",
            description=(
                f"{self.sender.mention} enviou "
                f"**{format_money(self.amount)}** para {self.receiver.mention}."
            ),
            color=discord.Color.green(),
        )
        embed.add_field(
            name=f"saldo de {self.sender.display_name}",
            value=format_money(sender_balance),
        )
        embed.add_field(
            name=f"saldo de {self.receiver.display_name}",
            value=format_money(receiver_balance),
        )

        await interaction.response.edit_message(embed=embed, view=self)
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
                f"**{format_money(self.amount)}** enviado por "
                f"{self.sender.mention}."
            ),
            color=discord.Color.red(),
        )

        await interaction.response.edit_message(embed=embed, view=self)
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
# SELEÇÃO DE PROFISSÃO
# ============================================================

class JobSelectView(discord.ui.View):
    def __init__(
        self,
        *,
        database: EconomyDatabase,
        guild_id: int,
        user_id: int,
    ):
        super().__init__(timeout=60)

        self.database = database
        self.guild_id = guild_id
        self.user_id = user_id
        self.finished = False

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "apenas quem iniciou a entrevista pode escolher a profissão.",
                ephemeral=True,
            )
            return False

        return True

    def disable_select(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Select):
                item.disabled = True

    @discord.ui.select(
        placeholder="selecione uma profissão",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(
                label=job.display_name,
                value=job.name,
                description=(
                    f"Salário: {format_money(job.salary)} | "
                    f"Chance: {job.approval_chance * 100:.0f}%"
                ),
            )
            for job in JobData
        ],
    )
    async def select_job(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select,
    ) -> None:
        if self.finished:
            await interaction.response.send_message(
                "esta entrevista já foi finalizada.",
                ephemeral=True,
            )
            return

        self.finished = True
        self.disable_select()

        selected_job = JobData[select.values[0]]

        current_job = await self.database.get_job(
            self.guild_id,
            self.user_id,
        )

        if current_job is not None:
            await interaction.response.edit_message(
                content="você já possui um emprego.",
                embed=None,
                view=self,
            )
            self.stop()
            return

        approved = random.random() < selected_job.approval_chance

        if not approved:
            next_interview = (
                await self.database.set_failed_interview_cooldown(
                    self.guild_id,
                    self.user_id,
                )
            )

            embed = discord.Embed(
                title="reprovado na entrevista",
                description=(
                    f"você não foi aprovado para a posição de "
                    f"**{selected_job.display_name}**."
                ),
                color=discord.Color.red(),
            )
            embed.add_field(
                name="chance de aprovação",
                value=f"{selected_job.approval_chance * 100:.0f}%",
                inline=True,
            )
            embed.add_field(
                name="próxima tentativa",
                value=f"<t:{next_interview}:R>",
                inline=True,
            )

            await interaction.response.edit_message(embed=embed, view=self)
            self.stop()
            return

        hired = await self.database.hire_employee(
            guild_id=self.guild_id,
            user_id=self.user_id,
            job_data=selected_job,
        )

        if not hired:
            await interaction.response.edit_message(
                content="você já possui um emprego.",
                embed=None,
                view=self,
            )
            self.stop()
            return

        embed = discord.Embed(
            title="parabéns, você foi aprovado!",
            description=(
                f"você agora trabalha como **{selected_job.display_name}**."
            ),
            color=discord.Color.green(),
        )
        embed.add_field(
            name="salário mensal",
            value=format_money(selected_job.salary),
            inline=True,
        )
        embed.add_field(
            name="meta mensal",
            value=f"{selected_job.monthly_goal} trabalhos",
            inline=True,
        )
        embed.add_field(
            name="próximo passo",
            value="use `/trabalhar` para começar.",
            inline=False,
        )

        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()


# ============================================================
# COG
# ============================================================

class Economia(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.database = EconomyDatabase(DATABASE_PATH)
        self.salary_loop.start()

    def cog_unload(self) -> None:
        self.salary_loop.cancel()

    @staticmethod
    def is_guild_owner(interaction: discord.Interaction) -> bool:
        return (
            interaction.guild is not None
            and interaction.guild.owner_id == interaction.user.id
        )

    @staticmethod
    async def ensure_correct_guild(
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.guild_id != ECONOMY_GUILD_ID:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "este sistema de economia não funciona neste servidor.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "este sistema de economia não funciona neste servidor.",
                    ephemeral=True,
                )
            return False

        return True

    @tasks.loop(minutes=1)
    async def salary_loop(self) -> None:
        try:
            payments = await self.database.process_due_salaries()

            for payment in payments:
                guild = self.bot.get_guild(payment["guild_id"])

                if guild is None:
                    continue

                member = guild.get_member(payment["user_id"])

                if member is None:
                    continue

                try:
                    await member.send(
                        (
                            f"seu ciclo mensal como **{payment['job_name']}** terminou.\n"
                            f"você recebeu **{format_money(payment['amount'])}**.\n"
                            f"próximo pagamento: <t:{payment['next_payment']}:R>."
                        )
                    )
                except discord.HTTPException:
                    pass

        except Exception as error:
            print(
                f"❌ Erro ao processar salários: "
                f"{type(error).__name__}: {error}"
            )

    @salary_loop.before_loop
    async def before_salary_loop(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="saldo",
        description="mostra seu saldo ou o saldo de outra pessoa.",
    )
    @app_commands.guilds(discord.Object(id=ECONOMY_GUILD_ID))
    @app_commands.describe(
        usuario="usuário cujo saldo será consultado.",
    )
    async def saldo(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member | None = None,
    ) -> None:
        target = usuario or interaction.user

        if not isinstance(target, discord.Member):
            await interaction.response.send_message(
                "não foi possível obter esse usuário.",
                ephemeral=True,
            )
            return

        balance = await self.database.get_balance(
            interaction.guild_id,
            target.id,
        )

        embed = discord.Embed(
            title=(
                "seu saldo"
                if usuario is None
                else f"saldo de {target.display_name}"
            ),
            description=f"**{format_money(balance)}**",
            color=(
                discord.Color.green()
                if usuario is None
                else discord.Color.blurple()
            ),
        )

        embed.set_thumbnail(url=target.display_avatar.url)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="addreais",
        description="adiciona reais ao saldo de um usuário.",
    )
    @app_commands.guilds(discord.Object(id=ECONOMY_GUILD_ID))
    @app_commands.describe(
        usuario="usuário que receberá os reais.",
        quantia="quantidade que será adicionada.",
    )
    async def addreais(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        quantia: app_commands.Range[
            int,
            MIN_TRANSACTION,
            MAX_TRANSACTION,
        ],
    ) -> None:
        if not self.is_guild_owner(interaction):
            await interaction.response.send_message(
                "apenas o dono com posse do servidor pode usar este comando.",
                ephemeral=True,
            )
            return

        new_balance = await self.database.add_money(
            interaction.guild_id,
            usuario.id,
            quantia,
        )

        await interaction.response.send_message(
            (
                f"adicionei **{format_money(quantia)}** para "
                f"{usuario.mention}.\n"
                f"novo saldo: **{format_money(new_balance)}**."
            )
        )

    @app_commands.command(
        name="remover_reais",
        description="remove reais do saldo de um usuário.",
    )
    @app_commands.guilds(discord.Object(id=ECONOMY_GUILD_ID))
    @app_commands.describe(
        usuario="usuário que terá reais removidos.",
        quantia="quantidade que será removida.",
    )
    async def remover_reais(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        quantia: app_commands.Range[
            int,
            MIN_TRANSACTION,
            MAX_TRANSACTION,
        ],
    ) -> None:
        if not self.is_guild_owner(interaction):
            await interaction.response.send_message(
                "apenas o dono com posse do servidor pode usar este comando.",
                ephemeral=True,
            )
            return

        success, balance = await self.database.remove_money(
            interaction.guild_id,
            usuario.id,
            quantia,
        )

        if not success:
            await interaction.response.send_message(
                (
                    f"{usuario.mention} não possui "
                    f"**{format_money(quantia)}**.\n"
                    f"saldo atual: **{format_money(balance)}**."
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            (
                f"removi **{format_money(quantia)}** de "
                f"{usuario.mention}.\n"
                f"novo saldo: **{format_money(balance)}**."
            )
        )

    @app_commands.command(
        name="daily",
        description="resgata uma recompensa diária.",
    )
    @app_commands.guilds(discord.Object(id=ECONOMY_GUILD_ID))
    async def daily(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "este comando só pode ser usado dentro do servidor.",
                ephemeral=True,
            )
            return

        base_amount = random.randint(100, 300)

        has_bonus_role = any(
            role.id in DAILY_BONUS_ROLE_IDS
            for role in interaction.user.roles
        )

        amount = int(base_amount * 1.5) if has_bonus_role else base_amount

        claimed, value, next_daily = await self.database.claim_daily(
            interaction.guild_id,
            interaction.user.id,
            amount,
        )

        if not claimed:
            await interaction.response.send_message(
                (
                    "você já resgatou seu daily.\n"
                    f"tente novamente <t:{next_daily}:R>."
                ),
                ephemeral=True,
            )
            return

        bonus_text = (
            "\nbônus de cargo **1,5x** aplicado."
            if has_bonus_role
            else ""
        )

        await interaction.response.send_message(
            (
                f"você recebeu **{format_money(amount)}** no daily."
                f"{bonus_text}\n"
                f"seu saldo agora é **{format_money(value)}**.\n"
                f"próximo daily: <t:{next_daily}:R>."
            )
        )

    @app_commands.command(
        name="pix",
        description="envia reais após a confirmação do destinatário.",
    )
    @app_commands.guilds(discord.Object(id=ECONOMY_GUILD_ID))
    @app_commands.describe(
        usuario="usuário que receberá o pix.",
        quantia="quantidade que será enviada.",
    )
    async def pix(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        quantia: app_commands.Range[int, MIN_PIX, MAX_TRANSACTION],
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "este comando só pode ser usado dentro do servidor.",
                ephemeral=True,
            )
            return

        if usuario.id == interaction.user.id:
            await interaction.response.send_message(
                "você não pode enviar pix para si mesmo.",
                ephemeral=True,
            )
            return

        if usuario.bot:
            await interaction.response.send_message(
                "você não pode enviar pix para bots.",
                ephemeral=True,
            )
            return

        sender_balance = await self.database.get_balance(
            interaction.guild_id,
            interaction.user.id,
        )

        if sender_balance < quantia:
            await interaction.response.send_message(
                (
                    "saldo insuficiente.\n"
                    f"você possui **{format_money(sender_balance)}**."
                ),
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
                f"**{format_money(quantia)}** para você.\n\n"
                "confirme ou recuse usando os botões abaixo."
            ),
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
        name="entrevista",
        description="participe de uma entrevista de emprego.",
    )
    @app_commands.guilds(discord.Object(id=ECONOMY_GUILD_ID))
    async def entrevista(
        self,
        interaction: discord.Interaction,
    ) -> None:
        job = await self.database.get_job(
            interaction.guild_id,
            interaction.user.id,
        )

        if job is not None:
            await interaction.response.send_message(
                "você já possui um emprego. use `/demitir` para sair dele.",
                ephemeral=True,
            )
            return

        next_interview = await self.database.get_interview_cooldown(
            interaction.guild_id,
            interaction.user.id,
        )

        if next_interview is not None:
            await interaction.response.send_message(
                (
                    "você foi reprovado recentemente.\n"
                    f"tente outra entrevista <t:{next_interview}:R>."
                ),
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
            description=(
                "selecione uma profissão abaixo.\n"
                "caso seja reprovado, haverá cooldown de 24 horas."
            ),
            color=discord.Color.blurple(),
        )

        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(
        name="trabalhar",
        description="registre um trabalho no seu emprego atual.",
    )
    @app_commands.guilds(discord.Object(id=ECONOMY_GUILD_ID))
    async def trabalhar(
        self,
        interaction: discord.Interaction,
    ) -> None:
        success, message = await self.database.work(
            interaction.guild_id,
            interaction.user.id,
        )

        await interaction.response.send_message(
            message,
            ephemeral=not success,
        )

    @app_commands.command(
        name="emprego",
        description="mostra informações sobre seu emprego atual.",
    )
    @app_commands.guilds(discord.Object(id=ECONOMY_GUILD_ID))
    async def emprego(
        self,
        interaction: discord.Interaction,
    ) -> None:
        job = await self.database.get_job(
            interaction.guild_id,
            interaction.user.id,
        )

        if job is None:
            await interaction.response.send_message(
                "você não possui emprego. use `/entrevista`.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="informações de emprego",
            description=f"✅ **{job['job_name']}**",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="salário mensal",
            value=format_money(int(job["salary"])),
            inline=True,
        )
        embed.add_field(
            name="meta mensal",
            value=(
                f"{int(job['work_count'])}/"
                f"{int(job['monthly_goal'])} trabalhos"
            ),
            inline=True,
        )
        embed.add_field(
            name="contratado em",
            value=f"<t:{int(job['hire_date'])}:d>",
            inline=True,
        )
        embed.add_field(
            name="próximo pagamento",
            value=f"<t:{int(job['next_payment_date'])}:R>",
            inline=True,
        )
        embed.add_field(
            name="infrações",
            value=f"{int(job['robbery_count'])}/7",
            inline=True,
        )

        if (
            job["status"] == JobStatus.AFASTADO.value
            and job["suspension_end_date"] is not None
        ):
            embed.add_field(
                name="afastado até",
                value=f"<t:{int(job['suspension_end_date'])}:f>",
                inline=False,
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
        success = await self.database.fire_employee(
            interaction.guild_id,
            interaction.user.id,
        )

        if not success:
            await interaction.response.send_message(
                "você não possui um emprego.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "você saiu do seu emprego.",
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Economia(bot))

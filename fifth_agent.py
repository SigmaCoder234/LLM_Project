"""
Агент №5 - Арбитр многоагентной системы модерации Telegram-бота

Этот агент принимает отчет от Агента №2, анализирует вердикты Агентов №3 и №4,
в случае конфликта принимает собственное решение, находит модератора в PostgreSQL
и отправляет финальный вердикт через REST API.

Требования:
- Python 3.10+
- asyncpg
- aiohttp

Установка:
pip install asyncpg aiohttp python-dotenv
"""

import asyncio
import logging
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime
import asyncpg
import aiohttp
import os
import json


# ============================================================================
# КОНФИГУРАЦИЯ И НАСТРОЙКИ
# ============================================================================

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('Agent5')


# ============================================================================
# КЛАССЫ ДАННЫХ (DATACLASSES)
# ============================================================================

class VerdictType(Enum):
    """Типы вердиктов для модерации"""
    APPROVE = "approve"          # Одобрить сообщение
    REJECT = "reject"            # Отклонить сообщение
    WARNING = "warning"          # Предупреждение
    BAN = "ban"                  # Бан пользователя
    UNCERTAIN = "uncertain"      # Неопределенно


@dataclass
class AgentVerdict:
    """Вердикт от одного агента (№3 или №4)"""
    agent_id: int                    # ID агента (3 или 4)
    verdict: VerdictType             # Тип вердикта
    confidence: float                # Уверенность в решении (0.0-1.0)
    reasoning: str                   # Обоснование решения
    timestamp: datetime              # Время вынесения вердикта

    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь для JSON"""
        return {
            'agent_id': self.agent_id,
            'verdict': self.verdict.value,
            'confidence': self.confidence,
            'reasoning': self.reasoning,
            'timestamp': self.timestamp.isoformat()
        }


@dataclass
class Agent2Report:
    """Отчет от Агента №2"""
    report_id: str                      # Уникальный ID отчета
    message_id: int                     # ID сообщения в Telegram
    chat_id: int                        # ID чата
    user_id: int                        # ID пользователя
    message_text: str                   # Текст сообщения
    agent3_verdict: AgentVerdict        # Вердикт агента №3
    agent4_verdict: AgentVerdict        # Вердикт агента №4
    is_conflicting: bool                # Есть ли конфликт между агентами
    metadata: Dict[str, Any]            # Дополнительные метаданные

    def has_conflict(self) -> bool:
        """Проверка наличия конфликта между вердиктами"""
        # Конфликт если вердикты разные или уверенность низкая
        verdicts_differ = self.agent3_verdict.verdict != self.agent4_verdict.verdict
        low_confidence = (
            self.agent3_verdict.confidence < 0.7 or 
            self.agent4_verdict.confidence < 0.7
        )
        return verdicts_differ or low_confidence


@dataclass
class Agent5Decision:
    """Финальное решение Агента №5"""
    decision_id: str                 # Уникальный ID решения
    report_id: str                   # ID исходного отчета
    final_verdict: VerdictType       # Финальный вердикт
    confidence: float                # Уверенность в решении
    reasoning: str                   # Обоснование решения
    agent3_verdict: VerdictType      # Вердикт агента №3
    agent4_verdict: VerdictType      # Вердикт агента №4
    was_conflict: bool               # Был ли конфликт
    timestamp: datetime              # Время принятия решения

    def to_json(self) -> str:
        """Конвертация в JSON для отправки в API"""
        return json.dumps({
            'decision_id': self.decision_id,
            'report_id': self.report_id,
            'final_verdict': self.final_verdict.value,
            'confidence': self.confidence,
            'reasoning': self.reasoning,
            'agent3_verdict': self.agent3_verdict.value,
            'agent4_verdict': self.agent4_verdict.value,
            'was_conflict': self.was_conflict,
            'timestamp': self.timestamp.isoformat()
        })


@dataclass
class ModeratorInfo:
    """Информация о модераторе из БД"""
    moderator_id: int                # ID модератора
    telegram_id: int                 # Telegram ID модератора
    username: str                    # Username модератора
    is_active: bool                  # Активен ли модератор
    api_endpoint: Optional[str]      # Персональный API endpoint (если есть)


# ============================================================================
# ОСНОВНОЙ КЛАСС АГЕНТА №5
# ============================================================================

class Agent5:
    """
    Агент №5 - Арбитр в системе модерации

    Принимает решения при спорных ситуациях между Агентами №3 и №4,
    находит модератора в базе данных и отправляет вердикт через REST API.
    """

    def __init__(
        self,
        db_config: Dict[str, Any],
        api_base_url: str,
        api_timeout: int = 30,
        max_retries: int = 3
    ):
        """
        Инициализация Агента №5

        Args:
            db_config: Конфигурация подключения к PostgreSQL
            api_base_url: Базовый URL REST API для отправки вердиктов
            api_timeout: Таймаут для HTTP запросов (секунды)
            max_retries: Максимальное количество попыток отправки
        """
        self.db_config = db_config
        self.api_base_url = api_base_url
        self.api_timeout = api_timeout
        self.max_retries = max_retries

        # Connection pool для PostgreSQL (будет инициализирован асинхронно)
        self.db_pool: Optional[asyncpg.Pool] = None

        # HTTP сессия для API запросов (будет инициализирована асинхронно)
        self.http_session: Optional[aiohttp.ClientSession] = None

        logger.info("Агент №5 создан")

    async def initialize(self):
        """Асинхронная инициализация соединений"""
        # Создание connection pool для PostgreSQL
        try:
            self.db_pool = await asyncpg.create_pool(
                **self.db_config,
                min_size=5,
                max_size=20,
                command_timeout=60
            )
            logger.info("✅ PostgreSQL connection pool инициализирован")
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации БД: {e}")
            raise

        # Создание HTTP сессии
        timeout = aiohttp.ClientTimeout(total=self.api_timeout)
        self.http_session = aiohttp.ClientSession(timeout=timeout)
        logger.info("✅ HTTP сессия инициализирована")

    async def cleanup(self):
        """Корректное закрытие всех соединений"""
        if self.db_pool:
            await self.db_pool.close()
            logger.info("PostgreSQL connection pool закрыт")

        if self.http_session:
            await self.http_session.close()
            logger.info("HTTP сессия закрыта")

    async def process_report(self, report: Agent2Report) -> bool:
        """
        Обработка отчета от Агента №2

        Args:
            report: Отчет от Агента №2

        Returns:
            bool: True если обработка успешна
        """
        logger.info(f"📥 Получен отчет {report.report_id} от Агента №2")

        try:
            # 1. Анализ отчета и принятие решения
            decision = await self.make_decision(report)
            logger.info(f"⚖️  Принято решение: {decision.final_verdict.value}")

            # 2. Получение информации о модераторе
            moderator = await self.get_moderator(report.chat_id)
            if not moderator:
                logger.error(f"❌ Модератор для чата {report.chat_id} не найден")
                return False

            logger.info(f"👤 Найден модератор: {moderator.username}")

            # 3. Отправка вердикта модератору через API
            success = await self.send_to_moderator(decision, moderator)

            if success:
                logger.info(f"✅ Вердикт успешно отправлен модератору {moderator.username}")
            else:
                logger.error(f"❌ Не удалось отправить вердикт модератору")

            return success

        except Exception as e:
            logger.error(f"❌ Ошибка обработки отчета: {e}", exc_info=True)
            return False

    async def make_decision(self, report: Agent2Report) -> Agent5Decision:
        """
        Принятие решения на основе вердиктов Агентов №3 и №4

        Логика принятия решения:
        1. Если вердикты совпадают и уверенность высокая - принимаем их решение
        2. Если есть конфликт - проводим собственный анализ
        3. Используем взвешенную оценку по уверенности агентов

        Args:
            report: Отчет от Агента №2

        Returns:
            Agent5Decision: Финальное решение
        """
        agent3 = report.agent3_verdict
        agent4 = report.agent4_verdict

        logger.info(f"🤔 Анализ вердиктов: Agent3={agent3.verdict.value} ({agent3.confidence:.2f}), "
                   f"Agent4={agent4.verdict.value} ({agent4.confidence:.2f})")

        # Проверка на конфликт
        has_conflict = report.has_conflict()

        if not has_conflict:
            # Вердикты совпадают и уверенность высокая
            final_verdict = agent3.verdict
            confidence = (agent3.confidence + agent4.confidence) / 2
            reasoning = (
                f"Агенты №3 и №4 согласны. "
                f"Средняя уверенность: {confidence:.2f}. "
                f"Обоснование Agent3: {agent3.reasoning}. "
                f"Обоснование Agent4: {agent4.reasoning}."
            )
            logger.info("✅ Конфликта нет, принимаем согласованное решение")
        else:
            # Есть конфликт - проводим собственный анализ
            logger.warning("⚠️  Обнаружен конфликт между агентами!")
            final_verdict, confidence, reasoning = await self._resolve_conflict(
                report, agent3, agent4
            )

        # Генерация уникального ID решения
        decision_id = f"decision_{report.report_id}_{int(datetime.now().timestamp())}"

        decision = Agent5Decision(
            decision_id=decision_id,
            report_id=report.report_id,
            final_verdict=final_verdict,
            confidence=confidence,
            reasoning=reasoning,
            agent3_verdict=agent3.verdict,
            agent4_verdict=agent4.verdict,
            was_conflict=has_conflict,
            timestamp=datetime.now()
        )

        return decision

    async def _resolve_conflict(
        self,
        report: Agent2Report,
        agent3: AgentVerdict,
        agent4: AgentVerdict
    ) -> tuple[VerdictType, float, str]:
        """
        Разрешение конфликта между агентами

        Стратегия:
        1. Анализ контекста сообщения
        2. Взвешенная оценка по уверенности агентов
        3. Применение собственных правил Агента №5

        Args:
            report: Отчет с информацией о сообщении
            agent3: Вердикт агента №3
            agent4: Вердикт агента №4

        Returns:
            tuple: (финальный_вердикт, уверенность, обоснование)
        """
        logger.info("🔍 Начинаю разрешение конфликта...")

        # Собственный анализ сообщения (упрощенная версия)
        message_analysis = await self._analyze_message(report.message_text)

        # Взвешенная оценка по уверенности
        weight3 = agent3.confidence
        weight4 = agent4.confidence
        total_weight = weight3 + weight4

        # Если один агент значительно увереннее другого
        if weight3 > 0.8 and weight4 < 0.6:
            final_verdict = agent3.verdict
            confidence = agent3.confidence * 0.9  # Немного снижаем уверенность
            reasoning = (
                f"Конфликт разрешен в пользу Агента №3 (уверенность {weight3:.2f}). "
                f"{agent3.reasoning}"
            )
        elif weight4 > 0.8 and weight3 < 0.6:
            final_verdict = agent4.verdict
            confidence = agent4.confidence * 0.9
            reasoning = (
                f"Конфликт разрешен в пользу Агента №4 (уверенность {weight4:.2f}). "
                f"{agent4.reasoning}"
            )
        else:
            # Применяем собственный анализ
            final_verdict = message_analysis['verdict']
            confidence = message_analysis['confidence']
            reasoning = (
                f"Конфликт разрешен собственным анализом Агента №5. "
                f"Agent3: {agent3.verdict.value} ({weight3:.2f}), "
                f"Agent4: {agent4.verdict.value} ({weight4:.2f}). "
                f"Решение: {message_analysis['reason']}"
            )

        logger.info(f"⚖️  Конфликт разрешен: {final_verdict.value} (уверенность: {confidence:.2f})")

        return final_verdict, confidence, reasoning

    async def _analyze_message(self, message_text: str) -> Dict[str, Any]:
        """
        Собственный анализ сообщения Агентом №5

        Это упрощенная версия. В реальной системе здесь может быть:
        - ML модель для классификации
        - Проверка по базе запрещенных слов
        - Анализ тональности
        - И т.д.

        Args:
            message_text: Текст сообщения для анализа

        Returns:
            dict: Результат анализа
        """
        # Имитация анализа (в реальности здесь сложная логика)
        # Например, проверка на спам-паттерны

        spam_keywords = ['купить', 'скидка', 'заработок', 'кликай', 'переходи']
        toxic_keywords = ['дурак', 'идиот', 'ненавижу']

        message_lower = message_text.lower()

        spam_count = sum(1 for keyword in spam_keywords if keyword in message_lower)
        toxic_count = sum(1 for keyword in toxic_keywords if keyword in message_lower)

        if toxic_count > 0:
            return {
                'verdict': VerdictType.WARNING,
                'confidence': 0.75,
                'reason': f'Обнаружены токсичные слова ({toxic_count})'
            }
        elif spam_count >= 2:
            return {
                'verdict': VerdictType.REJECT,
                'confidence': 0.70,
                'reason': f'Вероятный спам ({spam_count} спам-маркеров)'
            }
        else:
            return {
                'verdict': VerdictType.APPROVE,
                'confidence': 0.65,
                'reason': 'Сообщение выглядит безопасным'
            }

    async def get_moderator(self, chat_id: int) -> Optional[ModeratorInfo]:
        """
        Получение информации о модераторе из PostgreSQL

        Args:
            chat_id: ID чата в Telegram

        Returns:
            ModeratorInfo или None если модератор не найден
        """
        if not self.db_pool:
            raise RuntimeError("Database pool не инициализирован")

        try:
            async with self.db_pool.acquire() as conn:
                # Параметризованный запрос для безопасности
                query = """
                    SELECT 
                        m.id as moderator_id,
                        m.telegram_id,
                        m.username,
                        m.is_active,
                        m.api_endpoint
                    FROM moderators m
                    JOIN chat_moderators cm ON m.id = cm.moderator_id
                    WHERE cm.chat_id = $1 AND m.is_active = true
                    ORDER BY m.priority DESC
                    LIMIT 1
                """

                row = await conn.fetchrow(query, chat_id)

                if row:
                    moderator = ModeratorInfo(
                        moderator_id=row['moderator_id'],
                        telegram_id=row['telegram_id'],
                        username=row['username'],
                        is_active=row['is_active'],
                        api_endpoint=row.get('api_endpoint')
                    )
                    logger.info(f"✅ Модератор найден: {moderator.username}")
                    return moderator
                else:
                    logger.warning(f"⚠️  Модератор для чата {chat_id} не найден в БД")
                    return None

        except asyncpg.PostgresError as e:
            logger.error(f"❌ Ошибка PostgreSQL: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка получения модератора: {e}", exc_info=True)
            return None

    async def send_to_moderator(
        self,
        decision: Agent5Decision,
        moderator: ModeratorInfo
    ) -> bool:
        """
        Отправка вердикта модератору через REST API

        Реализует retry логику и обработку ошибок

        Args:
            decision: Решение для отправки
            moderator: Информация о модераторе

        Returns:
            bool: True если отправка успешна
        """
        if not self.http_session:
            raise RuntimeError("HTTP session не инициализирована")

        # Определяем endpoint (персональный или общий)
        if moderator.api_endpoint:
            url = moderator.api_endpoint
        else:
            url = f"{self.api_base_url}/moderator/{moderator.moderator_id}/verdict"

        # Подготовка данных для отправки
        payload = {
            'decision': decision.to_json(),
            'moderator_id': moderator.moderator_id,
            'telegram_id': moderator.telegram_id,
            'timestamp': datetime.now().isoformat()
        }

        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'TelegramModerationBot-Agent5/1.0'
        }

        # Попытки отправки с retry
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(f"📤 Попытка {attempt}/{self.max_retries}: отправка на {url}")

                async with self.http_session.post(
                    url,
                    json=payload,
                    headers=headers
                ) as response:

                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"✅ Вердикт успешно отправлен: {result}")
                        return True
                    elif response.status >= 500:
                        # Серверная ошибка - retry
                        logger.warning(f"⚠️  Серверная ошибка {response.status}, повтор...")
                        if attempt < self.max_retries:
                            await asyncio.sleep(2 ** attempt)  # Exponential backoff
                            continue
                    else:
                        # Клиентская ошибка - не retry
                        error_text = await response.text()
                        logger.error(f"❌ Ошибка API {response.status}: {error_text}")
                        return False

            except aiohttp.ClientError as e:
                logger.error(f"❌ HTTP ошибка (попытка {attempt}): {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
            except asyncio.TimeoutError:
                logger.error(f"❌ Таймаут (попытка {attempt})")
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
            except Exception as e:
                logger.error(f"❌ Неожиданная ошибка: {e}", exc_info=True)
                return False

        logger.error(f"❌ Не удалось отправить вердикт после {self.max_retries} попыток")
        return False


# ============================================================================
# ГЛАВНАЯ ФУНКЦИЯ И ПРИМЕР ИСПОЛЬЗОВАНИЯ
# ============================================================================

async def main():
    """
    Пример использования Агента №5
    """
    # Конфигурация подключения к PostgreSQL
    db_config = {
        'host': os.getenv('DB_HOST', 'localhost'),
        'port': int(os.getenv('DB_PORT', 5432)),
        'user': os.getenv('DB_USER', 'postgres'),
        'password': os.getenv('DB_PASSWORD', 'password'),
        'database': os.getenv('DB_NAME', 'telegram_moderation')
    }

    # Базовый URL REST API
    api_base_url = os.getenv('API_BASE_URL', 'http://localhost:8000/api/v1')

    # Создание и инициализация агента
    agent = Agent5(
        db_config=db_config,
        api_base_url=api_base_url,
        api_timeout=30,
        max_retries=3
    )

    try:
        await agent.initialize()
        logger.info("🚀 Агент №5 запущен и готов к работе")

        # Пример: создание тестового отчета от Агента №2
        # В реальной системе отчеты будут приходить из очереди сообщений (RabbitMQ, Kafka и т.д.)

        test_report = Agent2Report(
            report_id="report_12345",
            message_id=98765,
            chat_id=-1001234567890,
            user_id=123456789,
            message_text="Купить дешево! Кликай здесь для заработка!",
            agent3_verdict=AgentVerdict(
                agent_id=3,
                verdict=VerdictType.REJECT,
                confidence=0.85,
                reasoning="Обнаружены спам-паттерны",
                timestamp=datetime.now()
            ),
            agent4_verdict=AgentVerdict(
                agent_id=4,
                verdict=VerdictType.WARNING,
                confidence=0.65,
                reasoning="Возможный спам, требуется проверка",
                timestamp=datetime.now()
            ),
            is_conflicting=True,
            metadata={}
        )

        # Обработка отчета
        success = await agent.process_report(test_report)

        if success:
            logger.info("✅ Тестовый отчет успешно обработан")
        else:
            logger.error("❌ Ошибка обработки тестового отчета")

        # В реальной системе здесь был бы бесконечный цикл получения отчетов
        # Например:
        # while True:
        #     report = await get_report_from_queue()
        #     await agent.process_report(report)

    except KeyboardInterrupt:
        logger.info("⏸️  Получен сигнал остановки")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
    finally:
        await agent.cleanup()
        logger.info("👋 Агент №5 остановлен")


if __name__ == "__main__":
    """
    Точка входа в программу
    """
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Программа завершена пользователем")

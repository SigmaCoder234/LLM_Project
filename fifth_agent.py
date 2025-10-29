# -*- coding: utf-8 -*-
"""
АГЕНТ №5 - Финальный координатор решений (ГОТОВЫЙ ACCESS TOKEN)
Агент №5 получает результаты от Агентов 2, 3 и 4, принимает финальное решение
о модерации и отправляет уведомления модераторам через REST API.

Использует готовый Access Token для совместимости с обновленной архитектурой
(хотя сам не использует ГигаЧат напрямую)
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

# Настройки логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('Agent5')

# === НАСТРОЙКИ (ГОТОВЫЙ ACCESS TOKEN) ===
# ГигаЧат настройки - ГОТОВЫЙ ACCESS TOKEN (на случай если понадобится)
from token import TOKEN
GIGACHAT_ACCESS_TOKEN = TOKEN
# === ENUM И DATACLASS ===
class VerdictType(Enum):
    APPROVE = "approve"
    REJECT = "reject"
    WARNING = "warning"
    BAN = "ban"
    UNCERTAIN = "uncertain"

@dataclass
class AgentVerdict:
    """Решение от агентов 3 или 4"""
    agent_id: int  # ID агента (3 или 4)
    verdict: VerdictType
    confidence: float  # 0.0-1.0
    reasoning: str
    timestamp: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в JSON для API"""
        return {
            'agent_id': self.agent_id,
            'verdict': self.verdict.value,
            'confidence': self.confidence,
            'reasoning': self.reasoning,
            'timestamp': self.timestamp.isoformat()
        }

@dataclass
class Agent2Report:
    """Отчет от Агента 2"""
    report_id: str  # Уникальный ID отчета
    message_id: int  # ID сообщения Telegram
    chat_id: int  # ID чата
    user_id: int  # ID пользователя
    message_text: str
    agent3_verdict: AgentVerdict  # Решение от Агента 3
    agent4_verdict: AgentVerdict  # Решение от Агента 4
    is_conflicting: bool
    metadata: Dict[str, Any]
    
    def has_conflict(self) -> bool:
        """Проверка конфликта между агентами"""
        # Агенты дают разные вердикты
        verdicts_differ = self.agent3_verdict.verdict != self.agent4_verdict.verdict
        # Или низкая уверенность у одного из агентов
        low_confidence = self.agent3_verdict.confidence < 0.7 or self.agent4_verdict.confidence < 0.7
        return verdicts_differ or low_confidence

@dataclass
class Agent5Decision:
    """Финальное решение от Агента 5"""
    decision_id: str  # Уникальный ID решения
    report_id: str  # ID отчета из Agent2Report
    final_verdict: VerdictType
    confidence: float
    reasoning: str
    agent3_verdict: VerdictType  # Решение Агента 3
    agent4_verdict: VerdictType  # Решение Агента 4
    was_conflict: bool
    timestamp: datetime
    
    def to_json(self) -> str:
        """Конвертация в JSON для API"""
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
    moderator_id: int  # ID модератора
    telegram_id: int  # Telegram ID модератора
    username: str  # Username модератора
    is_active: bool
    api_endpoint: Optional[str]  # API endpoint для отправки уведомлений

# === ОСНОВНОЙ КЛАСС АГЕНТА 5 ===
class Agent5:
    """
    Агент №5 - финальный координатор решений.
    Анализирует результаты от Агентов 3 и 4, принимает финальное решение
    и отправляет уведомления модераторам через REST API.
    """
    
    def __init__(self, db_config: Dict[str, Any], api_base_url: str, api_timeout: int = 30, max_retries: int = 3):
        """
        Инициализация Агента 5
        
        Args:
            db_config: Конфигурация для подключения к PostgreSQL
            api_base_url: Базовый URL для REST API
            api_timeout: Таймаут для HTTP запросов
            max_retries: Максимальное количество попыток отправки
        """
        self.db_config = db_config
        self.api_base_url = api_base_url
        self.api_timeout = api_timeout
        self.max_retries = max_retries
        
        # Connection pool для PostgreSQL
        self.db_pool: Optional[asyncpg.Pool] = None
        
        # HTTP сессия для API вызовов
        self.http_session: Optional[aiohttp.ClientSession] = None
        
        logger.info("🤖 Агент 5 инициализирован (совместим с готовым Access Token)")
    
    async def initialize(self):
        """Инициализация подключений к БД и HTTP API"""
        try:
            # Создаем connection pool для PostgreSQL
            self.db_pool = await asyncpg.create_pool(**self.db_config, min_size=5, max_size=20, command_timeout=60)
            logger.info("✅ PostgreSQL connection pool создан")
        except Exception as e:
            logger.error(f"❌ Ошибка создания connection pool для PostgreSQL: {e}")
            raise
        
        # Создаем HTTP сессию
        timeout = aiohttp.ClientTimeout(total=self.api_timeout)
        self.http_session = aiohttp.ClientSession(timeout=timeout)
        logger.info("✅ HTTP сессия создана")
    
    async def cleanup(self):
        """Очистка ресурсов"""
        if self.db_pool:
            await self.db_pool.close()
            logger.info("🗄️  PostgreSQL connection pool закрыт")
        
        if self.http_session:
            await self.http_session.close()
            logger.info("🌐 HTTP сессия закрыта")
    
    async def process_report(self, report: Agent2Report) -> bool:
        """
        Обработка отчета от Агента 2
        
        Args:
            report: Отчет от Агента 2
        
        Returns:
            bool: True если отчет успешно обработан
        """
        logger.info(f"📋 Обрабатываем отчет {report.report_id} от Агента 2")
        
        try:
            # 1. Принимаем финальное решение
            decision = await self.make_decision(report)
            logger.info(f"⚖️  Финальное решение: {decision.final_verdict.value}")
            
            # 2. Получаем модератора для этого чата
            moderator = await self.get_moderator(report.chat_id)
            if not moderator:
                logger.error(f"❌ Не найден модератор для чата {report.chat_id}")
                return False
            
            logger.info(f"👤 Найден модератор: @{moderator.username}")
            
            # 3. Отправляем уведомление модератору через REST API
            success = await self.send_to_moderator(decision, moderator)
            if success:
                logger.info(f"✅ Уведомление отправлено модератору @{moderator.username}")
            else:
                logger.error(f"❌ Не удалось отправить уведомление модератору")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки отчета: {e}", exc_info=True)
            return False
    
    async def make_decision(self, report: Agent2Report) -> Agent5Decision:
        """
        Принятие финального решения на основе результатов от Агентов 3 и 4
        
        1. Если агенты согласны - принимаем их решение
        2. Если есть конфликт - используем дополнительную логику
        3. В крайнем случае передаем решение Агенту 5
        
        Args:
            report: Отчет от Агента 2
        
        Returns:
            Agent5Decision: Финальное решение
        """
        agent3 = report.agent3_verdict
        agent4 = report.agent4_verdict
        
        logger.info(f"🔍 Анализируем: Agent3={agent3.verdict.value}({agent3.confidence:.2f}), Agent4={agent4.verdict.value}({agent4.confidence:.2f})")
        
        # Проверяем наличие конфликта
        has_conflict = report.has_conflict()
        
        if not has_conflict:
            # Агенты согласны - принимаем их решение
            final_verdict = agent3.verdict
            confidence = (agent3.confidence + agent4.confidence) / 2
            reasoning = f"Агенты 3 и 4 согласны. Уверенность: {confidence:.2f}. " \
                       f"Agent3: {agent3.reasoning}. Agent4: {agent4.reasoning}."
            logger.info("✅ Агенты согласны, конфликта нет")
        else:
            # Есть конфликт - разрешаем его
            logger.warning("⚠️  Обнаружен конфликт между агентами!")
            final_verdict, confidence, reasoning = await self.resolve_conflict(report, agent3, agent4)
        
        # Создаем финальное решение
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
    
    async def resolve_conflict(self, report: Agent2Report, agent3: AgentVerdict, agent4: AgentVerdict) -> tuple[VerdictType, float, str]:
        """
        Разрешение конфликта между Агентами 3 и 4
        
        1. Анализируем уверенность агентов
        2. Используем дополнительные эвристики
        3. В крайнем случае применяем логику Агента 5
        
        Args:
            report: Отчет
            agent3: Решение Агента 3
            agent4: Решение Агента 4
        
        Returns:
            tuple: (финальный_вердикт, уверенность, обоснование)
        """
        logger.info("🔧 Разрешаем конфликт между агентами...")
        
        # Анализируем сообщение с помощью эвристики Агента 5
        message_analysis = await self.analyze_message(report.message_text) 
        
        # Взвешиваем решения агентов по уверенности
        weight3 = agent3.confidence
        weight4 = agent4.confidence
        
        # Если один агент очень уверен, а другой нет
        if weight3 > 0.8 and weight4 < 0.6:
            final_verdict = agent3.verdict
            confidence = agent3.confidence * 0.9
            reasoning = f"Приоритет Агенту 3 (уверенность {weight3:.2f}). {agent3.reasoning}"
        elif weight4 > 0.8 and weight3 < 0.6:
            final_verdict = agent4.verdict
            confidence = agent4.confidence * 0.9
            reasoning = f"Приоритет Агенту 4 (уверенность {weight4:.2f}). {agent4.reasoning}"
        else:
            # Используем анализ Агента 5
            final_verdict = message_analysis['verdict']
            confidence = message_analysis['confidence']
            reasoning = f"Решение Агента 5 из-за конфликта. Agent3: {agent3.verdict.value} ({weight3:.2f}), Agent4: {agent4.verdict.value} ({weight4:.2f}). {message_analysis['reason']}"
        
        logger.info(f"⚖️  Конфликт разрешен: {final_verdict.value} (уверенность: {confidence:.2f})")
        return final_verdict, confidence, reasoning
    
    async def analyze_message(self, message_text: str) -> Dict[str, Any]:
        """
        Анализ сообщения силами Агента 5.
        Простая эвристика для разрешения конфликтов.
        
        - Может быть заменена на ML модель
        - Может использовать готовый Access Token при необходимости
        - Может анализировать дополнительные факторы
        
        Args:
            message_text: Текст сообщения
        
        Returns:
            dict: {'verdict': VerdictType, 'confidence': float, 'reason': str}
        """
        # Простые ключевые слова для анализа
        spam_keywords = ['дешево', 'скидка', 'купи', 'продаж', 'реклам', 'заработок', 'акция']
        toxic_keywords = ['идиот', 'дурак', 'тупой', 'урод', 'козёл']
        profanity_keywords = ['бля', 'хуй', 'пизд', 'ебал']
        
        message_lower = message_text.lower()
        
        spam_count = sum(1 for keyword in spam_keywords if keyword in message_lower)
        toxic_count = sum(1 for keyword in toxic_keywords if keyword in message_lower)
        profanity_count = sum(1 for keyword in profanity_keywords if keyword in message_lower)
        
        if profanity_count > 0:
            return {
                'verdict': VerdictType.BAN,
                'confidence': 0.85,
                'reason': f"Обнаружен мат: {profanity_count} слов"
            }
        elif toxic_count > 0:
            return {
                'verdict': VerdictType.WARNING,
                'confidence': 0.75,
                'reason': f"Обнаружены токсичные слова: {toxic_count}"
            }
        elif spam_count >= 2:
            return {
                'verdict': VerdictType.REJECT,
                'confidence': 0.70,
                'reason': f"Вероятный спам - найдено ключевых слов: {spam_count}"
            }
        else:
            return {
                'verdict': VerdictType.APPROVE,
                'confidence': 0.65,
                'reason': "Сообщение прошло базовую проверку Агента 5"
            }
    
    async def get_moderator(self, chat_id: int) -> Optional[ModeratorInfo]:
        """
        Получение модератора для чата из PostgreSQL
        
        Args:
            chat_id: ID чата Telegram
        
        Returns:
            ModeratorInfo или None если модератор не найден
        """
        if not self.db_pool:
            raise RuntimeError("Database pool не инициализирован")
        
        try:
            async with self.db_pool.acquire() as conn:
                # Ищем активного модератора для чата, упорядоченного по приоритету
                query = """
                    SELECT m.id as moderator_id, m.telegram_id, m.username, m.is_active, m.api_endpoint
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
                    logger.info(f"👤 Найден модератор: @{moderator.username}")
                    return moderator
                else:
                    logger.warning(f"⚠️  Не найден активный модератор для чата {chat_id}")
                    return None
                    
        except asyncpg.PostgresError as e:
            logger.error(f"❌ Ошибка PostgreSQL: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка: {e}", exc_info=True)
            return None
    
    async def send_to_moderator(self, decision: Agent5Decision, moderator: ModeratorInfo) -> bool:
        """
        Отправка уведомления модератору через REST API с retry логикой
        
        Args:
            decision: Финальное решение
            moderator: Информация о модераторе
        
        Returns:
            bool: True если уведомление отправлено успешно
        """
        if not self.http_session:
            # HTTP сессия не инициализирована
            raise RuntimeError("HTTP session не инициализирована")
        
        # Определяем endpoint для отправки
        if moderator.api_endpoint:
            url = moderator.api_endpoint
        else:
            url = f"{self.api_base_url}/moderator/{moderator.moderator_id}/verdict"
        
        # Формируем payload для API
        payload = {
            'decision': asdict(decision),
            'moderator_id': moderator.moderator_id, 
            'telegram_id': moderator.telegram_id,
            'timestamp': datetime.now().isoformat()
        }
        
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'TelegramModerationBot-Agent5/1.0'
        }
        
        # Retry логика
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(f"🌐 Попытка {attempt}/{self.max_retries}: отправляем в {url}")
                
                async with self.http_session.post(url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"✅ API ответ: {result}")
                        return True
                    elif response.status >= 500:
                        # Серверные ошибки - можно retry
                        logger.warning(f"⚠️  Серверная ошибка {response.status}, попытка повтора...")
                        if attempt < self.max_retries:
                            await asyncio.sleep(2 ** attempt)  # Exponential backoff
                            continue
                    else:
                        # Клиентские ошибки - не retry
                        error_text = await response.text()
                        logger.error(f"❌ Ошибка API {response.status}: {error_text}")
                        return False
                        
            except aiohttp.ClientError as e:
                logger.error(f"❌ HTTP клиентская ошибка (попытка {attempt}): {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
            except asyncio.TimeoutError:
                logger.error(f"⏰ Таймаут запроса (попытка {attempt})")
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
            except Exception as e:
                logger.error(f"❌ Неожиданная ошибка: {e}", exc_info=True)
                return False
        
        logger.error(f"❌ Исчерпаны все {self.max_retries} попытки отправки")
        return False

# === MAIN ФУНКЦИЯ ===
async def main():
    """Главная функция для тестирования Агента 5"""
    
    # Конфигурация PostgreSQL
    db_config = {
        'host': os.getenv('DB_HOST', '176.108.248.211'),
        'port': int(os.getenv('DB_PORT', 5432)),
        'user': os.getenv('DB_USER', 'tguser'),
        'password': os.getenv('DB_PASSWORD', 'mnvm7110'),
        'database': os.getenv('DB_NAME', 'teleguard_db')
    }
    
    # Базовый URL для REST API
    api_base_url = os.getenv('API_BASE_URL', 'http://localhost:8000/api/v1')
    
    # Создаем экземпляр Агента 5
    agent = Agent5(
        db_config=db_config,
        api_base_url=api_base_url,
        api_timeout=30,
        max_retries=3
    )
    
    try:
        await agent.initialize()
        logger.info("🚀 Агент 5 инициализирован")
        
        # Тестовый отчет
        test_report = Agent2Report(
            report_id="report_12345",
            message_id=98765,
            chat_id=-1001234567890,
            user_id=123456789,
            message_text="Купите дешевые айфоны! Скидки!!!",
            agent3_verdict=AgentVerdict(
                agent_id=3,
                verdict=VerdictType.REJECT,
                confidence=0.85,
                reasoning="Обнаружена реклама - запрещено",
                timestamp=datetime.now()
            ),
            agent4_verdict=AgentVerdict(
                agent_id=4,
                verdict=VerdictType.WARNING,
                confidence=0.65,
                reasoning="Подозрительное сообщение, но не критично",
                timestamp=datetime.now()
            ),
            is_conflicting=True,
            metadata={}
        )
        
        # Обрабатываем тестовый отчет
        # Здесь можно добавить логику получения отчетов из RabbitMQ, Kafka и т.д.
        success = await agent.process_report(test_report)
        
        if success:
            logger.info("✅ Тестовый отчет успешно обработан")
        else:
            logger.error("❌ Ошибка обработки тестового отчета")
        
    except KeyboardInterrupt:
        logger.info("⏹️  Получен сигнал остановки")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
    finally:
        await agent.cleanup()
        logger.info("👋 Агент 5 завершил работу")

if __name__ == "__main__":
    print("=" * 60)
    print("🔧 АГЕНТ №5 - ГОТОВЫЙ ACCESS TOKEN")
    print("=" * 60)
    print("🤖 Финальный координатор решений")
    print("🔑 Совместим с готовым Access Token")
    print(f"📏 Длина токена: {len(GIGACHAT_ACCESS_TOKEN)} символов")
    print("🧪 Поддерживает проверку из Telegram бота")
    print()
    print("✨ Возможности:")
    print("   • Анализ решений от Агентов 3 и 4")
    print("   • Разрешение конфликтов между агентами")
    print("   • Отправка уведомлений модераторам")
    print("   • PostgreSQL интеграция")
    print("   • REST API коммуникация")
    print()
    print("📝 Хотя Агент 5 не использует ГигаЧат напрямую,")
    print("    он совместим с обновленной архитектурой")
    print()
    print("🚀 Запускаем Агент 5...")
    print("=" * 60)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹️  Программа остановлена пользователем")

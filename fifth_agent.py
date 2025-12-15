#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""

🤖 АГЕНТ №5 — АРБИТР И МОДЕРАТОР

✅ Получает решения от агентов 3 и 4

✅ Сравнивает их решения

✅ При разногласиях использует OpenAI для финального вердикта

✅ Пишет результаты в Redis

✅ БОТ читает результаты и отправляет модераторам чата

"""

import json

import redis

import time

import asyncio

from typing import Dict, Any, List

from datetime import datetime

import aiohttp

import requests

from config import (

    get_redis_config,

    QUEUE_AGENT_5_INPUT,

    QUEUE_AGENT_5_OUTPUT,

    TELEGRAM_BOT_TOKEN,

    setup_logging,

    DEFAULT_RULES,

)

# ============================================================================

# ЛОГИРОВАНИЕ

# ============================================================================

logger = setup_logging("АГЕНТ 5")

# ============================================================================

# OPENAI API КОНФИГУРАЦИЯ

# ============================================================================

OPENAI_API_KEY = OPENAI_TOKEN

OPENAI_MODEL = "gpt-4o-mini"

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

# ============================================================================

# TELEGRAM API

# ============================================================================

TELEGRAM_API_URL = "https://api.telegram.org"

async def apply_moderation_action(chat_id: int, user_id: int,

    action: str, duration: int = 0) -> bool:

    # Применяет действие модерации (ban/mute/warn)

    try:

        url = f"{TELEGRAM_API_URL}/bot{TELEGRAM_BOT_TOKEN}"

        if action.lower() == "ban":

            async with aiohttp.ClientSession() as session:

                async with session.post(

                    f"{url}/banChatMember",

                    json={

                        "chat_id": chat_id,

                        "user_id": user_id,

                        "revoke_messages": True

                    },

                    timeout=aiohttp.ClientTimeout(total=10)

                ) as resp:

                    if resp.status == 200:

                        logger.info(f"🚫 Пользователь {user_id} забанен в чате {chat_id}")

                        return True

        elif action.lower() == "mute":

            until_date = int(time.time()) + (duration * 60)

            async with aiohttp.ClientSession() as session:

                async with session.post(

                    f"{url}/restrictChatMember",

                    json={

                        "chat_id": chat_id,

                        "user_id": user_id,

                        "permissions": {

                            "can_send_messages": False,

                            "can_send_media_messages": False,

                            "can_send_other_messages": False,

                            "can_add_web_page_previews": False

                        },

                        "until_date": until_date

                    },

                    timeout=aiohttp.ClientTimeout(total=10)

                ) as resp:

                    if resp.status == 200:

                        logger.info(f"🔇 Пользователь {user_id} замучен на {duration} мин")

                        return True

        elif action.lower() == "warn":

            logger.warning(f"⚠️ Предупреждение для {user_id} в чате {chat_id}")

            return True

        return False

    except Exception as e:

        logger.error(f"❌ Ошибка при применении действия: {e}")

        return False

# ============================================================================

# OPENAI АРБИТР

# ============================================================================

def call_openai_for_verdict(message: str, agent3_decision: Dict[str, Any], 

    agent4_decision: Dict[str, Any]) -> Dict[str, Any]:

    try:

        rules_text = "\n".join([f"- {rule}" for rule in DEFAULT_RULES])

        prompt = f"""Ты опытный модератор сообщества. Проанализируй следующее сообщение и два решения от разных модераторов.

ПРАВИЛА СООБЩЕСТВА:
{rules_text}

СООБЩЕНИЕ ДЛЯ АНАЛИЗА:
"{message}"

РЕШЕНИЕ МОДЕРАТОРА 3:
- Действие: {agent3_decision.get('action', 'none')}
- Серьезность: {agent3_decision.get('severity', 0)}/10
- Уверенность: {agent3_decision.get('confidence', 0)}%

РЕШЕНИЕ МОДЕРАТОРА 4:
- Действие: {agent4_decision.get('action', 'none')}
- Серьезность: {agent4_decision.get('severity', 0)}/10
- Уверенность: {agent4_decision.get('confidence', 0)}%

Дай финальный вердикт в формате JSON:
{{
    "final_action": "none|warn|mute|ban",
    "final_severity": число от 0 до 10,
    "final_confidence": число от 0 до 100,
    "reasoning": "краткое объяснение решения",
    "violated_rule": "какое правило нарушено (если есть)"
}}

Будь объективен и справедлив. Верни ТОЛЬКО JSON без дополнительного текста."""

        headers = {

            "Authorization": f"Bearer {OPENAI_API_KEY}",

            "Content-Type": "application/json"

        }

        payload = {

            "model": OPENAI_MODEL,

            "messages": [

                {

                    "role": "user",

                    "content": prompt

                }

            ],

            "temperature": 0.3,

            "max_tokens": 300

        }

        logger.info("🤖 Отправляю запрос к OpenAI для арбитража...")

        response = requests.post(OPENAI_API_URL, json=payload, headers=headers, timeout=15)

        if response.status_code != 200:

            logger.error(f"❌ OpenAI API ошибка: {response.status_code}")

            raise Exception(f"API error: {response.status_code}")

        response_data = response.json()

        ai_response = response_data["choices"][0]["message"]["content"]

        try:

            verdict = json.loads(ai_response)

            logger.info(f"✅ Получен вердикт от OpenAI: {verdict['final_action']}")

            return verdict

        except json.JSONDecodeError:

            logger.error(f"❌ Не удалось распарсить JSON из ответа OpenAI: {ai_response}")

            raise Exception("Failed to parse AI response as JSON")

    except requests.exceptions.Timeout:

        logger.error("❌ Timeout при обращении к OpenAI API")

        raise Exception("API timeout")

    except Exception as e:

        logger.error(f"❌ Ошибка при вызове OpenAI: {e}")

        raise

# ============================================================================

# СРАВНЕНИЕ РЕШЕНИЙ АГЕНТОВ

# ============================================================================

def compare_agent_decisions(agent3_result: Dict[str, Any], 

                           agent4_result: Dict[str, Any]) -> Dict[str, Any]:

    """

    Сравнивает решения агентов 3 и 4

    Если согласны - принимает решение

    Если расходятся - вызывает OpenAI

    """

    logger.info("🔀 Сравниваю решения Агента 3 и Агента 4...")

    agent3_action = agent3_result.get("action", "none").lower()

    agent4_action = agent4_result.get("action", "none").lower()

    agent3_severity = agent3_result.get("severity", 0)

    agent4_severity = agent4_result.get("severity", 0)

    agent3_confidence = agent3_result.get("confidence", 0)

    agent4_confidence = agent4_result.get("confidence", 0)

    message = agent4_result.get("message", "")



    actions_match = agent3_action == agent4_action

    severity_diff = abs(agent3_severity - agent4_severity)

    logger.info(f"📊 Агент 3: {agent3_action} (severity={agent3_severity})")

    logger.info(f"📊 Агент 4: {agent4_action} (severity={agent4_severity})")

    logger.info(f"📊 Разница в серьезности: {severity_diff}/10")

    if actions_match and severity_diff <= 2:

        # Агенты согласны - принимаем их решение

        logger.info("✅ Агенты согласны! Принимаю их вердикт")

        return {

            "consensus": True,

            "final_action": agent3_action,

            "final_severity": (agent3_severity + agent4_severity) // 2,

            "final_confidence": min(agent3_confidence, agent4_confidence),

            "reasoning": "Оба агента согласны с решением",

            "decision_source": "consensus"

        }

    else:

        # Агенты расходятся - вызываем OpenAI

        logger.warning("⚠️ Агенты расходятся! Вызываю OpenAI для арбитража...")

        try:

            openai_verdict = call_openai_for_verdict(message, agent3_result, agent4_result)

            logger.info(f"✅ OpenAI вынес вердикт: {openai_verdict['final_action']}")

            return {

                "consensus": False,

                "final_action": openai_verdict.get("final_action", "none"),

                "final_severity": openai_verdict.get("final_severity", 0),

                "final_confidence": openai_verdict.get("final_confidence", 0),

                "reasoning": openai_verdict.get("reasoning", "OpenAI арбитраж"),

                "violated_rule": openai_verdict.get("violated_rule", ""),

                "decision_source": "openai_arbitrage"

            }

        except Exception as e:

            logger.error(f"❌ Ошибка при вызове OpenAI, использую консервативный подход: {e}")

            # Консервативный подход - берем более мягкое решение

            if agent3_action in ["none", "warn"]:

                final_action = agent3_action

            elif agent4_action in ["none", "warn"]:

                final_action = agent4_action

            else:

                final_action = agent3_action  # Если оба строгие - берем первого

            return {

                "consensus": False,

                "final_action": final_action,

                "final_severity": min(agent3_severity, agent4_severity),

                "final_confidence": 50,

                "reasoning": "Консервативное решение при ошибке OpenAI",

                "decision_source": "fallback"

            }

# ============================================================================

# ОСНОВНАЯ ФУНКЦИЯ АГЕНТА 5

# ============================================================================

async def process_moderation_result(result_data: Dict[str, Any]) -> Dict[str, Any]:

    try:

        message = result_data.get("message", "")

        chat_id = result_data.get("chat_id", 0)

        user_id = result_data.get("user_id", 0)

        username = result_data.get("username", "unknown")

        message_id = result_data.get("message_id", 0)

        message_link = result_data.get("message_link", "")

        logger.info(f"🔍 Обрабатываю результат от агента 4 для @{username}")

        # Сравниваем решения агентов 3 и 4

        final_decision = compare_agent_decisions(result_data, result_data)

        final_action = final_decision.get("final_action", "none").lower()

        final_severity = final_decision.get("final_severity", 0)

        final_confidence = final_decision.get("final_confidence", 0)

        final_reasoning = final_decision.get("reasoning", "")

        consensus = final_decision.get("consensus", False)

        decision_source = final_decision.get("decision_source", "unknown")

        logger.info(f"📋 Финальное решение: {final_action} (серьезность={final_severity}/10, уверенность={final_confidence}%)")

        # Если нарушение обнаружено

        if final_action in ["ban", "mute", "warn"]:

            # Определяем длительность для mute

            if final_action == "mute":

                if final_severity >= 8:

                    duration = 1440  

                elif final_severity >= 6:

                    duration = 360  

                else:

                    duration = 120 

            else:

                duration = 0

            await apply_moderation_action(

                chat_id=chat_id,

                user_id=user_id,

                action=final_action,

                duration=duration

            )

            logger.info(f"✅ Действие {final_action} применено для @{username}")

            output = {

                "agent_id": 5,

                "status": "processed",

                "action": final_action,

                "user": username,

                "user_id": user_id,

                "chat_id": chat_id,

                "message_id": message_id,

                "message_link": message_link,

                "message_text": message[:200],

                "severity": final_severity,

                "confidence": final_confidence,

                "reason": final_reasoning,

                "consensus": consensus,

                "decision_source": decision_source,

                "violated_rule": final_decision.get("violated_rule", ""),

                "timestamp": datetime.now().isoformat()

            }

            return output

        else:

            logger.info(f"✅ Сообщение от @{username} в порядке (нет нарушений)")

            output = {

                "agent_id": 5,

                "status": "ok",

                "action": "none",

                "user": username,

                "user_id": user_id,

                "chat_id": chat_id,

                "message_id": message_id,

                "message_link": message_link,

                "message_text": message[:200],

                "severity": 0,

                "confidence": final_confidence,

                "reason": "Нарушений не обнаружено",

                "consensus": consensus,

                "decision_source": decision_source,

                "timestamp": datetime.now().isoformat()

            }

            return output

    except Exception as e:

        logger.error(f"❌ Ошибка обработки: {e}")

        return {

            "agent_id": 5,

            "status": "error",

            "error": str(e),

            "timestamp": datetime.now().isoformat()

        }

# ============================================================================

# REDIS WORKER

# ============================================================================

class Agent5Worker:

    def __init__(self):

        try:

            redis_config = get_redis_config()

            self.redis_client = redis.Redis(**redis_config)

            self.redis_client.ping()

            logger.info("✅ Подключение к Redis успешно")

        except Exception as e:

            logger.error(f"❌ Не удалось подключиться к Redis: {e}")

            raise

    def run(self):

        logger.info("✅ Агент 5 запущен (Арбитр + OpenAI + Модератор)")

        logger.info(f"📬 Слушаю очередь: {QUEUE_AGENT_5_INPUT}")

        logger.info(f"📤 Результаты в очередь: {QUEUE_AGENT_5_OUTPUT}")

        logger.info("🤖 Использую OpenAI для арбитража при разногласиях")

        logger.info("⏱️ Нажмите Ctrl+C для остановки\n")

        try:

            while True:

                try:

                    result = self.redis_client.blpop(QUEUE_AGENT_5_INPUT, timeout=1)

                    if result is None:

                        continue

                    queue_name, message_data = result

                    logger.info("📨 Получено решение для обработки")

                    # Парсим JSON

                    try:

                        input_data = json.loads(message_data)

                    except json.JSONDecodeError as e:

                        logger.error(f"❌ Невалидный JSON: {e}")

                        continue

                    # Обрабатываем асинхронно

                    output = asyncio.run(process_moderation_result(input_data))

                    # ✅ ПИШЕМ РЕЗУЛЬТАТ В REDIS для БОТа

                    try:

                        result_json = json.dumps(output, ensure_ascii=False)

                        self.redis_client.rpush(QUEUE_AGENT_5_OUTPUT, result_json)

                        action = output.get("action", "none")

                        source = output.get("decision_source", "unknown")

                        logger.info(f"📤 ✅ Результат в Redis: action={action}, source={source}")

                    except Exception as e:

                        logger.error(f"❌ Ошибка отправки результата в Redis: {e}")

                    logger.info("✅ Обработка завершена\n")

                except Exception as e:

                    logger.error(f"❌ Ошибка в цикле: {e}")

                    time.sleep(1)

        except KeyboardInterrupt:

            logger.info("\n❌ Агент 5 остановлен (Ctrl+C)")

        finally:

            logger.info("Агент 5 завершил работу")

# ============================================================================

# ТОЧКА ВХОДА

# ============================================================================

if __name__ == "__main__":

    try:

        worker = Agent5Worker()

        worker.run()

    except KeyboardInterrupt:

        logger.info("Выход")

    except Exception as e:

        logger.error(f"❌ Критическая ошибка: {e}")

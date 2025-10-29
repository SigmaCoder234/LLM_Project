#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ЧАТ-АГЕНТ №4 - Эвристический модератор
"""

import asyncio
import logging
import redis
import json
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_HOST = "localhost"
REDIS_PORT = 6379

# Список матерных слов для эвристического анализа
BANNED_WORDS = ['мат', 'спам', 'реклама']

class Agent4:
    def __init__(self):
        try:
            self.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            self.redis_client.ping()
            logger.info("🚀 Агент №4 инициализирован")
        except Exception as e:
            logger.error(f"❌ Ошибка Redis: {e}")
            self.redis_client = None
    
    def run(self):
        logger.info("✅ Агент №4 запущен и слушает очередь")
        asyncio.run(self.listen())
    
    async def check_heuristic(self, text):
        """Эвристический анализ"""
        text_lower = text.lower()
        for word in BANNED_WORDS:
            if word in text_lower:
                return True
        return False
    
    async def listen(self):
        try:
            while True:
                if self.redis_client:
                    try:
                        msg = self.redis_client.blpop("queue:agent4_input", timeout=1)
                        if msg:
                            data = json.loads(msg[1])
                            is_violation = await self.check_heuristic(data.get('text', ''))
                            logger.info(f"📨 Анализ: {'⚠️ нарушение' if is_violation else '✅ чистое'}")
                    except:
                        pass
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("❌ Агент №4 остановлен")

if __name__ == "__main__":
    agent = Agent4()
    agent.run()

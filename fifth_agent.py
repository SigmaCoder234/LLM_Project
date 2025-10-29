#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ЧАТ-АГЕНТ №5 - Финальный арбитр
"""

import asyncio
import logging
import redis
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_HOST = "localhost"
REDIS_PORT = 6379

class Agent5:
    def __init__(self):
        try:
            self.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            self.redis_client.ping()
            logger.info("🚀 Агент №5 инициализирован")
        except Exception as e:
            logger.error(f"❌ Ошибка Redis: {e}")
            self.redis_client = None
    
    def run(self):
        logger.info("✅ Агент №5 запущен и слушает очередь")
        asyncio.run(self.listen())
    
    async def make_decision(self, agent3_result, agent4_result):
        """Принимает финальное решение"""
        if agent3_result or agent4_result:
            return True
        return False
    
    async def listen(self):
        try:
            while True:
                if self.redis_client:
                    try:
                        # Получаем результаты от агентов
                        msg3 = self.redis_client.blpop("queue:agent3_output", timeout=1)
                        msg4 = self.redis_client.blpop("queue:agent4_output", timeout=1)
                        
                        if msg3 or msg4:
                            logger.info(f"📨 Принято решение от агентов")
                    except:
                        pass
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("❌ Агент №5 остановлен")

if __name__ == "__main__":
    agent = Agent5()
    agent.run()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ЧАТ-АГЕНТ №2 - Обработчик сообщений
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Agent2:
    def __init__(self):
        logger.info("🚀 Агент №2 инициализирован")
    
    def run(self):
        logger.info("✅ Агент №2 запущен и слушает очередь")
        asyncio.run(self.listen())
    
    async def listen(self):
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("❌ Агент №2 остановлен")

if __name__ == "__main__":
    agent = Agent2()
    agent.run()

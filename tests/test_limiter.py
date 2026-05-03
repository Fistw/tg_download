import pytest
import time
import asyncio

from src.limiter import FloodWaitCoordinator, RetryStrategy, get_flood_coordinator


class TestFloodWaitCoordinator:
    @pytest.mark.asyncio
    async def test_init(self):
        coord = FloodWaitCoordinator()
        assert coord.is_waiting is False
        assert coord.remaining_wait == 0.0
    
    @pytest.mark.asyncio
    async def test_set_wait(self):
        coord = FloodWaitCoordinator()
        await coord.set_wait(5)
        assert coord.is_waiting is True
        assert 0.0 < coord.remaining_wait <= 5.0
    
    @pytest.mark.asyncio
    async def test_reset(self):
        coord = FloodWaitCoordinator()
        await coord.set_wait(10)
        coord.reset()
        assert coord.is_waiting is False
        assert coord.remaining_wait == 0.0
    
    @pytest.mark.asyncio
    async def test_wait_if_needed(self):
        coord = FloodWaitCoordinator()
        # 第一次调用不应该等待
        start = time.time()
        await coord.wait_if_needed()
        elapsed = time.time() - start
        assert elapsed < 1.0
    
    @pytest.mark.asyncio
    async def test_global_coordinator(self):
        coord1 = get_flood_coordinator()
        coord2 = get_flood_coordinator()
        assert coord1 is coord2


class TestRetryStrategy:
    def test_init_defaults(self):
        strategy = RetryStrategy()
        assert strategy.base_delay == 1.0
        assert strategy.max_delay == 60.0
        assert strategy.max_retries == 10
        assert strategy.jitter_factor == 0.2
    
    def test_init_custom(self):
        strategy = RetryStrategy(base_delay=2.0, max_delay=30.0, max_retries=5, jitter_factor=0.1)
        assert strategy.base_delay == 2.0
        assert strategy.max_delay == 30.0
        assert strategy.max_retries == 5
        assert strategy.jitter_factor == 0.1
    
    def test_should_retry(self):
        strategy = RetryStrategy(max_retries=3)
        assert strategy.should_retry(0) is True
        assert strategy.should_retry(1) is True
        assert strategy.should_retry(2) is True
        assert strategy.should_retry(3) is False
        assert strategy.should_retry(4) is False
    
    def test_get_delay_exponential(self):
        strategy = RetryStrategy(base_delay=1.0, max_delay=60.0, jitter_factor=0.0)
        # 无抖动时应该严格按照指数增长
        assert strategy.get_delay(0) == 1.0
        assert strategy.get_delay(1) == 2.0
        assert strategy.get_delay(2) == 4.0
        assert strategy.get_delay(3) == 8.0
    
    def test_get_delay_max_limit(self):
        strategy = RetryStrategy(base_delay=10.0, max_delay=30.0, jitter_factor=0.0)
        # 超过最大值时应该被截断
        assert strategy.get_delay(0) == 10.0
        assert strategy.get_delay(1) == 20.0
        assert strategy.get_delay(2) == 30.0
        assert strategy.get_delay(3) == 30.0
        assert strategy.get_delay(10) == 30.0
    
    def test_get_delay_jitter(self):
        strategy = RetryStrategy(base_delay=10.0, max_delay=60.0, jitter_factor=0.5)
        # 带抖动时应该在一定范围内
        delays = {strategy.get_delay(1) for _ in range(100)}
        # 抖动范围应该在 10-30 之间 (20 * 0.5 = ±10)
        for d in delays:
            assert 10.0 <= d <= 30.0
        # 不应该所有值都一样
        assert len(delays) > 1
    
    def test_get_delay_negative_attempt(self):
        strategy = RetryStrategy()
        assert strategy.get_delay(-1) == 0.0

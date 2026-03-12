package com.reviewer.config.properties

import org.springframework.boot.context.properties.ConfigurationProperties

@ConfigurationProperties(prefix = "review-bot.redis-stream")
data class RedisStreamProperties(
    val streamKey: String = "review-requests",
    val consumerGroup: String = "review-workers",
    val consumerName: String = "worker-1",
)

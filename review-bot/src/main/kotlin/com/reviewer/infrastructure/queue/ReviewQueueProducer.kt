package com.reviewer.infrastructure.queue

import com.reviewer.config.properties.RedisStreamProperties
import io.github.oshai.kotlinlogging.KotlinLogging
import kotlinx.coroutines.reactor.awaitSingle
import org.springframework.data.redis.connection.stream.StreamRecords
import org.springframework.data.redis.core.ReactiveRedisTemplate
import org.springframework.stereotype.Component

private val logger = KotlinLogging.logger {}

@Component
class ReviewQueueProducer(
    private val redisTemplate: ReactiveRedisTemplate<String, String>,
    private val redisStreamProperties: RedisStreamProperties,
) {
    suspend fun enqueue(message: ReviewMessage) {
        val record = StreamRecords.newRecord()
            .`in`(redisStreamProperties.streamKey)
            .ofMap(
                mapOf(
                    "reviewRequestId" to message.reviewRequestId,
                    "repositoryFullName" to message.repositoryFullName,
                    "pullRequestNumber" to message.pullRequestNumber.toString(),
                ),
            )

        redisTemplate.opsForStream<String, String>()
            .add(record)
            .awaitSingle()

        logger.info { "Enqueued review request: ${message.reviewRequestId}" }
    }
}

package com.reviewer.infrastructure.queue

import com.reviewer.config.properties.ReviewProperties
import io.github.oshai.kotlinlogging.KotlinLogging
import kotlinx.coroutines.reactor.awaitSingle
import org.springframework.data.redis.connection.stream.ObjectRecord
import org.springframework.data.redis.connection.stream.StreamRecords
import org.springframework.data.redis.core.ReactiveRedisTemplate
import org.springframework.stereotype.Component
import tools.jackson.databind.ObjectMapper

private val logger = KotlinLogging.logger {}

@Component
class ReviewQueueProducer(
    private val redisTemplate: ReactiveRedisTemplate<String, String>,
    private val objectMapper: ObjectMapper,
    private val reviewProperties: ReviewProperties,
) {

    suspend fun enqueue(message: ReviewMessage) {
        val json = objectMapper.writeValueAsString(message)

        val record: ObjectRecord<String, String> = StreamRecords
            .newRecord()
            .ofObject(json)
            .withStreamKey(reviewProperties.streamKey)

        val recordId = redisTemplate.opsForStream<String, String>()
            .add(record)
            .awaitSingle()

        logger.info {
            "Enqueued review message: reviewRequestId=${message.reviewRequestId}, " +
                "repo=${message.repositoryFullName}, PR=#${message.pullRequestNumber}, " +
                "recordId=$recordId"
        }
    }
}

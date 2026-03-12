package com.reviewer.infrastructure.queue

import com.reviewer.config.properties.RedisStreamProperties
import com.reviewer.domain.service.ReviewService
import io.github.oshai.kotlinlogging.KotlinLogging
import jakarta.annotation.PostConstruct
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.reactor.awaitSingle
import kotlinx.coroutines.reactor.awaitSingleOrNull
import org.springframework.data.redis.connection.stream.Consumer
import org.springframework.data.redis.connection.stream.ReadOffset
import org.springframework.data.redis.connection.stream.StreamOffset
import org.springframework.data.redis.connection.stream.StreamReadOptions
import org.springframework.data.redis.core.ReactiveRedisTemplate
import org.springframework.stereotype.Component

private val logger = KotlinLogging.logger {}

@Component
class ReviewQueueConsumer(
    private val redisTemplate: ReactiveRedisTemplate<String, String>,
    private val redisStreamProperties: RedisStreamProperties,
    private val reviewService: ReviewService,
) {
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    @PostConstruct
    fun start() {
        scope.launch {
            initializeConsumerGroup()
            consume()
        }
    }

    private suspend fun initializeConsumerGroup() {
        try {
            redisTemplate.opsForStream<String, String>()
                .createGroup(redisStreamProperties.streamKey, redisStreamProperties.consumerGroup)
                .awaitSingleOrNull()
            logger.info { "Created consumer group: ${redisStreamProperties.consumerGroup}" }
        } catch (e: Exception) {
            logger.debug { "Consumer group already exists or stream not ready: ${e.message}" }
        }
    }

    private suspend fun consume() {
        val options = StreamReadOptions.empty()
            .count(1)
            .block(java.time.Duration.ofSeconds(5))
        val consumer = Consumer.from(redisStreamProperties.consumerGroup, redisStreamProperties.consumerName)

        while (scope.isActive) {
            try {
                val messages = redisTemplate.opsForStream<String, String>()
                    .read(
                        consumer, options,
                        StreamOffset.create(redisStreamProperties.streamKey, ReadOffset.lastConsumed()),
                    )
                    .collectList()
                    .awaitSingle()

                for (message in messages) {
                    val body = message.value
                    val reviewRequestId = body["reviewRequestId"] ?: continue

                    try {
                        logger.info { "Processing review request: $reviewRequestId" }
                        reviewService.processReview(reviewRequestId)

                        redisTemplate.opsForStream<String, String>()
                            .acknowledge(redisStreamProperties.consumerGroup, message)
                            .awaitSingle()
                    } catch (e: Exception) {
                        logger.error(e) { "Failed to process review: $reviewRequestId" }
                    }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                logger.error(e) { "Error in consumer loop" }
                delay(5000)
            }
        }
    }
}

package com.reviewer.infrastructure.queue

import com.reviewer.config.properties.ReviewProperties
import com.reviewer.domain.service.ReviewService
import io.github.oshai.kotlinlogging.KotlinLogging
import jakarta.annotation.PostConstruct
import jakarta.annotation.PreDestroy
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.reactive.asFlow
import kotlinx.coroutines.reactor.awaitSingleOrNull
import org.springframework.data.redis.connection.stream.Consumer
import org.springframework.data.redis.connection.stream.ObjectRecord
import org.springframework.data.redis.connection.stream.ReadOffset
import org.springframework.data.redis.connection.stream.StreamOffset
import org.springframework.data.redis.core.ReactiveRedisTemplate
import org.springframework.data.redis.stream.StreamReceiver
import org.springframework.stereotype.Component
import tools.jackson.databind.ObjectMapper

private val logger = KotlinLogging.logger {}

@Component
class ReviewQueueConsumer(
    private val streamReceiver: StreamReceiver<String, ObjectRecord<String, String>>,
    private val redisTemplate: ReactiveRedisTemplate<String, String>,
    private val objectMapper: ObjectMapper,
    private val reviewService: ReviewService,
    private val reviewProperties: ReviewProperties,
) {

    private val scope = CoroutineScope(Dispatchers.Default + SupervisorJob())

    @PostConstruct
    fun startConsuming() {
        scope.launch {
            ensureConsumerGroup()
            consumeMessages()
        }
    }

    @PreDestroy
    fun stopConsuming() {
        logger.info { "Stopping review queue consumer" }
        scope.cancel()
    }

    private suspend fun ensureConsumerGroup() {
        try {
            redisTemplate.opsForStream<String, String>()
                .createGroup(reviewProperties.streamKey, reviewProperties.consumerGroup)
                .awaitSingleOrNull()
            logger.info { "Created consumer group: ${reviewProperties.consumerGroup}" }
        } catch (e: Exception) {
            // Group may already exist
            logger.debug { "Consumer group already exists or stream not created yet: ${e.message}" }
        }
    }

    private suspend fun consumeMessages() {
        val consumer = Consumer.from(
            reviewProperties.consumerGroup,
            reviewProperties.consumerName,
        )
        val offset = StreamOffset.create(
            reviewProperties.streamKey,
            ReadOffset.lastConsumed(),
        )

        logger.info {
            "Starting to consume messages from stream=${reviewProperties.streamKey}, " +
                "group=${reviewProperties.consumerGroup}, consumer=${reviewProperties.consumerName}"
        }

        try {
            streamReceiver.receive(consumer, offset)
                .asFlow()
                .collect { record ->
                    processRecord(record)
                }
        } catch (e: Exception) {
            logger.error(e) { "Error in message consumption loop" }
        }
    }

    private suspend fun processRecord(record: ObjectRecord<String, String>) {
        val recordId = record.id.value
        try {
            val message = objectMapper.readValue(record.value, ReviewMessage::class.java)

            logger.info {
                "Processing review message: recordId=$recordId, " +
                    "reviewRequestId=${message.reviewRequestId}, " +
                    "repo=${message.repositoryFullName}#${message.pullRequestNumber}"
            }

            reviewService.processReview(message.reviewRequestId)

            // ACK the message
            redisTemplate.opsForStream<String, String>()
                .acknowledge(reviewProperties.streamKey, reviewProperties.consumerGroup, recordId)
                .awaitSingleOrNull()

            logger.info { "Acknowledged message: recordId=$recordId" }
        } catch (e: Exception) {
            logger.error(e) { "Failed to process message: recordId=$recordId" }
            // Message will remain pending and can be picked up by another consumer or retried
        }
    }
}

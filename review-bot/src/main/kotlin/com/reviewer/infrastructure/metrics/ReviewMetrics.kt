package com.reviewer.infrastructure.metrics

import io.micrometer.core.instrument.Counter
import io.micrometer.core.instrument.MeterRegistry
import io.micrometer.core.instrument.Timer
import org.springframework.stereotype.Component
import java.time.Duration

@Component
class ReviewMetrics(
    private val meterRegistry: MeterRegistry,
) {

    // --- Counters ---

    private val reviewRequestCounter = Counter.builder("review.requests.total")
        .description("Total number of review requests received")
        .register(meterRegistry)

    private val reviewCompletedCounter = Counter.builder("review.completed.total")
        .description("Total number of reviews completed")
        .register(meterRegistry)

    private val reviewFailedCounter = Counter.builder("review.failed.total")
        .description("Total number of reviews failed")
        .register(meterRegistry)

    private val reviewSkippedCounter = Counter.builder("review.skipped.total")
        .description("Total number of reviews skipped")
        .register(meterRegistry)

    private val commentsPostedCounter = Counter.builder("review.comments.posted.total")
        .description("Total number of review comments posted")
        .register(meterRegistry)

    private val fallbackCounter = Counter.builder("review.llm.fallback.total")
        .description("Total number of LLM fallbacks triggered")
        .register(meterRegistry)

    private val webhookReceivedCounter = Counter.builder("review.webhook.received.total")
        .description("Total number of webhooks received")
        .register(meterRegistry)

    // --- Timers ---

    private val reviewProcessingTimer = Timer.builder("review.processing.duration")
        .description("Time taken to process a review")
        .register(meterRegistry)

    private val llmCallTimer = Timer.builder("review.llm.call.duration")
        .description("Time taken for LLM API calls")
        .register(meterRegistry)

    // --- Methods ---

    fun incrementReviewRequests() {
        reviewRequestCounter.increment()
    }

    fun incrementReviewCompleted() {
        reviewCompletedCounter.increment()
    }

    fun incrementReviewFailed() {
        reviewFailedCounter.increment()
    }

    fun incrementReviewSkipped() {
        reviewSkippedCounter.increment()
    }

    fun incrementCommentsPosted(count: Int = 1) {
        commentsPostedCounter.increment(count.toDouble())
    }

    fun incrementFallbackCount() {
        fallbackCounter.increment()
    }

    fun incrementWebhookReceived() {
        webhookReceivedCounter.increment()
    }

    fun recordProcessingTime(durationMs: Long) {
        reviewProcessingTimer.record(Duration.ofMillis(durationMs))
    }

    fun recordLlmCallTime(durationMs: Long) {
        llmCallTimer.record(Duration.ofMillis(durationMs))
    }

    fun recordLlmCall(provider: String, success: Boolean) {
        Counter.builder("review.llm.calls.total")
            .tag("provider", provider)
            .tag("success", success.toString())
            .register(meterRegistry)
            .increment()
    }
}

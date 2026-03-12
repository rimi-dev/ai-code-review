package com.reviewer.infrastructure.metrics

import io.micrometer.core.instrument.Counter
import io.micrometer.core.instrument.MeterRegistry
import io.micrometer.core.instrument.Timer
import org.springframework.stereotype.Component
import java.time.Duration
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

@Component
class ReviewMetrics(
    private val registry: MeterRegistry,
) {
    // === Gauge backing fields ===
    private val circuitStateByProvider = ConcurrentHashMap<String, AtomicInteger>()
    private val queueDepthGauge = AtomicInteger(0)

    init {
        registry.gauge("queue.depth", queueDepthGauge) { it.toDouble() }
    }

    // ──────────────────────────────────────────────
    // review.total  (Counter: provider, status)
    // ──────────────────────────────────────────────
    fun incrementReviewTotal(provider: String, status: String) {
        Counter.builder("review.total")
            .tag("provider", provider)
            .tag("status", status)
            .description("Total review count")
            .register(registry)
            .increment()
    }

    // ──────────────────────────────────────────────
    // review.duration.ms  (Timer)
    // ──────────────────────────────────────────────
    fun recordReviewDuration(duration: Duration) {
        Timer.builder("review.duration.ms")
            .description("Review processing duration")
            .register(registry)
            .record(duration)
    }

    fun <T> recordReviewDuration(block: () -> T): T {
        return Timer.builder("review.duration.ms")
            .description("Review processing duration")
            .register(registry)
            .recordCallable(block)!!
    }

    // ──────────────────────────────────────────────
    // review.tokens.total  (Counter: provider, direction)
    // ──────────────────────────────────────────────
    fun incrementTokens(provider: String, direction: String, amount: Double) {
        Counter.builder("review.tokens.total")
            .tag("provider", provider)
            .tag("direction", direction)
            .description("Total token usage")
            .register(registry)
            .increment(amount)
    }

    // ──────────────────────────────────────────────
    // review.cost.usd  (Counter: provider)
    // ──────────────────────────────────────────────
    fun incrementCost(provider: String, amount: Double) {
        Counter.builder("review.cost.usd")
            .tag("provider", provider)
            .description("LLM cost in USD")
            .register(registry)
            .increment(amount)
    }

    // ──────────────────────────────────────────────
    // review.fallback.total  (Counter)
    // ──────────────────────────────────────────────
    fun incrementFallback() {
        Counter.builder("review.fallback.total")
            .description("Total fallback occurrences")
            .register(registry)
            .increment()
    }

    // ──────────────────────────────────────────────
    // review.comments.total  (Counter: category, severity)
    // ──────────────────────────────────────────────
    fun incrementComments(category: String, severity: String, amount: Double = 1.0) {
        Counter.builder("review.comments.total")
            .tag("category", category)
            .tag("severity", severity)
            .description("Total review comments")
            .register(registry)
            .increment(amount)
    }

    // ──────────────────────────────────────────────
    // model.circuit.state  (Gauge: provider)
    // 0 = CLOSED, 1 = HALF_OPEN, 2 = OPEN
    // ──────────────────────────────────────────────
    fun recordCircuitState(provider: String, state: Int) {
        val gauge = circuitStateByProvider.computeIfAbsent(provider) { key ->
            val atomicInt = AtomicInteger(state)
            registry.gauge("model.circuit.state", listOf(io.micrometer.core.instrument.Tag.of("provider", key)), atomicInt) { it.toDouble() }
            atomicInt
        }
        gauge.set(state)
    }

    // ──────────────────────────────────────────────
    // webhook.received.total  (Counter)
    // ──────────────────────────────────────────────
    fun incrementWebhookReceived() {
        Counter.builder("webhook.received.total")
            .description("Total webhooks received")
            .register(registry)
            .increment()
    }

    // ──────────────────────────────────────────────
    // queue.depth  (Gauge)
    // ──────────────────────────────────────────────
    fun recordQueueDepth(depth: Int) {
        queueDepthGauge.set(depth)
    }

    fun incrementQueueDepth() {
        queueDepthGauge.incrementAndGet()
    }

    fun decrementQueueDepth() {
        queueDepthGauge.decrementAndGet()
    }
}

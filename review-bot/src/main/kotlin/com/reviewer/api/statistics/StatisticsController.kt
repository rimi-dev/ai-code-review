package com.reviewer.api.statistics

import com.reviewer.api.dto.ReviewStatsResponse
import com.reviewer.domain.model.ReviewStatus
import com.reviewer.domain.repository.ReviewRequestRepository
import kotlinx.coroutines.flow.toList
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/v1/statistics")
class StatisticsController(
    private val reviewRequestRepository: ReviewRequestRepository,
) {
    @GetMapping
    suspend fun getStatistics(): ReviewStatsResponse {
        val allReviews = reviewRequestRepository.findAll().toList()
        val completed = allReviews.filter { it.status == ReviewStatus.COMPLETED }
        val failed = allReviews.filter { it.status == ReviewStatus.FAILED }

        val byProvider = completed.flatMap { it.reviews }
            .groupBy { it.provider.split(" ").first() }
            .mapValues { it.value.size.toLong() }

        val byCategory = completed.flatMap { it.reviews }
            .flatMap { it.comments }
            .groupBy { it.category }
            .mapValues { it.value.size.toLong() }

        val avgLatency = completed.flatMap { it.reviews }
            .map { it.latencyMs }
            .takeIf { it.isNotEmpty() }
            ?.average() ?: 0.0

        return ReviewStatsResponse(
            totalReviews = allReviews.size.toLong(),
            completedReviews = completed.size.toLong(),
            failedReviews = failed.size.toLong(),
            byProvider = byProvider,
            byCategory = byCategory,
            avgLatencyMs = avgLatency,
        )
    }
}

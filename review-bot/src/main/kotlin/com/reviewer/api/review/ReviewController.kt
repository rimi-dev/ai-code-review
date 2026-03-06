package com.reviewer.api.review

import com.reviewer.api.dto.response.ReviewCommentResponse
import com.reviewer.api.dto.response.ReviewDetailResponse
import com.reviewer.api.dto.response.ReviewResponse
import com.reviewer.api.dto.response.ReviewStatsResponse
import com.reviewer.api.exception.ApiException
import com.reviewer.domain.model.ReviewStatus
import com.reviewer.domain.repository.ReviewCommentRepository
import com.reviewer.domain.repository.ReviewRequestRepository
import io.github.oshai.kotlinlogging.KotlinLogging
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.toList
import org.springframework.data.domain.PageRequest
import org.springframework.http.HttpStatus
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController

private val logger = KotlinLogging.logger {}

@RestController
@RequestMapping("/api/v1/reviews")
class ReviewController(
    private val reviewRequestRepository: ReviewRequestRepository,
    private val reviewCommentRepository: ReviewCommentRepository,
) {

    @GetMapping
    fun listReviews(
        @RequestParam(required = false) repositoryFullName: String?,
        @RequestParam(required = false) status: ReviewStatus?,
        @RequestParam(defaultValue = "0") page: Int,
        @RequestParam(defaultValue = "20") size: Int,
    ): Flow<ReviewResponse> {
        val pageable = PageRequest.of(page, size)

        return when {
            repositoryFullName != null -> {
                reviewRequestRepository.findByRepositoryFullNameOrderByCreatedAtDesc(
                    repositoryFullName,
                    pageable,
                ).map { ReviewResponse.from(it) }
            }
            status != null -> {
                reviewRequestRepository.findByStatusOrderByCreatedAtDesc(
                    status,
                    pageable,
                ).map { ReviewResponse.from(it) }
            }
            else -> {
                reviewRequestRepository.findAll()
                    .map { ReviewResponse.from(it) }
            }
        }
    }

    @GetMapping("/{id}")
    suspend fun getReview(@PathVariable id: String): ReviewDetailResponse {
        val reviewRequest = reviewRequestRepository.findById(id)
            ?: throw ApiException(
                status = HttpStatus.NOT_FOUND,
                message = "Review not found: $id",
                errorCode = "review_not_found",
            )

        val comments = reviewCommentRepository
            .findByReviewRequestIdOrderByCreatedAtAsc(id)
            .map { ReviewCommentResponse.from(it) }
            .toList()

        return ReviewDetailResponse(
            review = ReviewResponse.from(reviewRequest),
            comments = comments,
        )
    }

    @GetMapping("/stats")
    suspend fun getStats(
        @RequestParam(required = false) repositoryFullName: String?,
    ): ReviewStatsResponse {
        val totalReviews: Long
        val completedReviews: Long
        val failedReviews: Long
        val skippedReviews: Long
        val queuedReviews: Long

        if (repositoryFullName != null) {
            totalReviews = reviewRequestRepository.findByRepositoryFullNameOrderByCreatedAtDesc(
                repositoryFullName,
                PageRequest.of(0, 1),
            ).toList().size.toLong().let {
                // For count, we use the count method
                var count = 0L
                ReviewStatus.entries.forEach { status ->
                    count += reviewRequestRepository.countByRepositoryFullNameAndStatus(
                        repositoryFullName,
                        status,
                    )
                }
                count
            }
            completedReviews = reviewRequestRepository.countByRepositoryFullNameAndStatus(
                repositoryFullName,
                ReviewStatus.COMPLETED,
            )
            failedReviews = reviewRequestRepository.countByRepositoryFullNameAndStatus(
                repositoryFullName,
                ReviewStatus.FAILED,
            )
            skippedReviews = reviewRequestRepository.countByRepositoryFullNameAndStatus(
                repositoryFullName,
                ReviewStatus.SKIPPED,
            )
            queuedReviews = reviewRequestRepository.countByRepositoryFullNameAndStatus(
                repositoryFullName,
                ReviewStatus.QUEUED,
            )
        } else {
            completedReviews = reviewRequestRepository.countByStatus(ReviewStatus.COMPLETED)
            failedReviews = reviewRequestRepository.countByStatus(ReviewStatus.FAILED)
            skippedReviews = reviewRequestRepository.countByStatus(ReviewStatus.SKIPPED)
            queuedReviews = reviewRequestRepository.countByStatus(ReviewStatus.QUEUED)
            totalReviews = completedReviews + failedReviews + skippedReviews + queuedReviews +
                reviewRequestRepository.countByStatus(ReviewStatus.PROCESSING)
        }

        val totalComments = reviewCommentRepository.count()

        // Calculate averages from completed reviews
        val completedReviewsList = reviewRequestRepository.findByStatusOrderByCreatedAtDesc(
            ReviewStatus.COMPLETED,
            PageRequest.of(0, 1000),
        ).toList()

        val averageProcessingTimeMs = if (completedReviewsList.isNotEmpty()) {
            completedReviewsList.map { it.processingTimeMs }.average()
        } else {
            0.0
        }

        val averageCommentsPerReview = if (completedReviewsList.isNotEmpty()) {
            completedReviewsList.map { it.commentCount.toDouble() }.average()
        } else {
            0.0
        }

        return ReviewStatsResponse(
            totalReviews = totalReviews,
            completedReviews = completedReviews,
            failedReviews = failedReviews,
            skippedReviews = skippedReviews,
            queuedReviews = queuedReviews,
            totalComments = totalComments,
            averageProcessingTimeMs = averageProcessingTimeMs,
            averageCommentsPerReview = averageCommentsPerReview,
        )
    }
}

package com.reviewer.api.review

import com.reviewer.api.dto.ReviewResponse
import com.reviewer.api.exception.ApiException
import com.reviewer.domain.model.ReviewStatus
import com.reviewer.domain.repository.ReviewRequestRepository
import com.reviewer.infrastructure.queue.ReviewMessage
import com.reviewer.infrastructure.queue.ReviewQueueProducer
import kotlinx.coroutines.flow.toList
import org.springframework.http.HttpStatus
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController
import java.time.Instant

@RestController
@RequestMapping("/api/v1/reviews")
class ReviewController(
    private val reviewRequestRepository: ReviewRequestRepository,
    private val queueProducer: ReviewQueueProducer,
) {
    @GetMapping
    suspend fun list(
        @RequestParam(required = false) repository: String?,
        @RequestParam(required = false) status: String?,
    ): List<ReviewResponse> {
        val reviews = if (repository != null) {
            reviewRequestRepository.findByRepositoryFullName(repository)
        } else if (status != null) {
            reviewRequestRepository.findByStatus(ReviewStatus.valueOf(status.uppercase()))
        } else {
            reviewRequestRepository.findAll().toList()
        }
        return reviews.map { ReviewResponse.from(it) }
    }

    @GetMapping("/{id}")
    suspend fun get(@PathVariable id: String): ReviewResponse {
        val review = reviewRequestRepository.findById(id)
            ?: throw ApiException(HttpStatus.NOT_FOUND, "Review not found")
        return ReviewResponse.from(review)
    }

    @PostMapping("/{id}/retry")
    suspend fun retry(@PathVariable id: String): ReviewResponse {
        val review = reviewRequestRepository.findById(id)
            ?: throw ApiException(HttpStatus.NOT_FOUND, "Review not found")

        if (review.status != ReviewStatus.FAILED) {
            throw ApiException(HttpStatus.BAD_REQUEST, "Only failed reviews can be retried")
        }

        val retried = review.copy(
            status = ReviewStatus.PENDING,
            updatedAt = Instant.now(),
        )
        val saved = reviewRequestRepository.save(retried)

        queueProducer.enqueue(
            ReviewMessage(
                reviewRequestId = saved.id!!,
                repositoryFullName = saved.repositoryFullName,
                pullRequestNumber = saved.platformPrId,
            ),
        )

        return ReviewResponse.from(saved)
    }
}

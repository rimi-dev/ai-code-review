package com.reviewer.domain.repository

import com.reviewer.domain.model.ReviewRequest
import com.reviewer.domain.model.ReviewStatus
import org.springframework.data.repository.kotlin.CoroutineCrudRepository

interface ReviewRequestRepository : CoroutineCrudRepository<ReviewRequest, String> {
    suspend fun findByRepositoryFullNameAndPlatformPrId(
        repositoryFullName: String,
        platformPrId: Int,
    ): ReviewRequest?

    suspend fun findByStatus(status: ReviewStatus): List<ReviewRequest>

    suspend fun findByRepositoryFullName(repositoryFullName: String): List<ReviewRequest>
}

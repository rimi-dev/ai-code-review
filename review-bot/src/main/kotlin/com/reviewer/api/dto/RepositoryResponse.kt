package com.reviewer.api.dto

import com.reviewer.domain.model.RegisteredRepository
import com.reviewer.domain.model.RepositorySettings
import com.reviewer.domain.model.ReviewRule
import java.time.Instant

data class RepositoryResponse(
    val id: String,
    val platform: String,
    val fullName: String,
    val isActive: Boolean,
    val settings: RepositorySettings,
    val reviewRules: List<ReviewRule>,
    val modelPreference: String,
    val createdAt: Instant?,
) {
    companion object {
        fun from(repo: RegisteredRepository) = RepositoryResponse(
            id = repo.id!!,
            platform = repo.platform,
            fullName = repo.fullName,
            isActive = repo.isActive,
            settings = repo.settings,
            reviewRules = repo.reviewRules,
            modelPreference = repo.modelPreference,
            createdAt = repo.createdAt,
        )
    }
}

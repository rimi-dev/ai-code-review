package com.reviewer.api.dto.response

import com.reviewer.domain.model.RegisteredRepository
import com.reviewer.domain.model.ReviewConfig
import java.time.Instant

data class RepositoryResponse(
    val id: String,
    val fullName: String,
    val owner: String,
    val name: String,
    val installationId: Long,
    val enabled: Boolean,
    val reviewConfig: ReviewConfig,
    val createdAt: Instant?,
    val updatedAt: Instant?,
) {
    companion object {
        fun from(entity: RegisteredRepository): RepositoryResponse {
            return RepositoryResponse(
                id = entity.id ?: "",
                fullName = entity.fullName,
                owner = entity.owner,
                name = entity.name,
                installationId = entity.installationId,
                enabled = entity.enabled,
                reviewConfig = entity.reviewConfig,
                createdAt = entity.createdAt,
                updatedAt = entity.updatedAt,
            )
        }
    }
}

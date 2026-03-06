package com.reviewer.api.dto.request

import com.reviewer.domain.model.ReviewConfig

data class RegisterRepositoryRequest(
    val fullName: String,
    val installationId: Long,
    val reviewConfig: ReviewConfig? = null,
)

data class UpdateRepositoryRequest(
    val enabled: Boolean? = null,
    val reviewConfig: ReviewConfig? = null,
)

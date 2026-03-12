package com.reviewer.api.dto

import com.reviewer.domain.model.RepositorySettings
import com.reviewer.domain.model.ReviewRule

data class CreateRepositoryRequest(
    val fullName: String,
    val installationId: Long,
    val webhookSecret: String? = null,
    val accessToken: String? = null,
    val settings: RepositorySettings? = null,
    val modelPreference: String? = null,
)

data class UpdateRepositoryRequest(
    val isActive: Boolean? = null,
    val settings: RepositorySettings? = null,
    val modelPreference: String? = null,
)

data class UpdateReviewRulesRequest(
    val rules: List<ReviewRule>,
)

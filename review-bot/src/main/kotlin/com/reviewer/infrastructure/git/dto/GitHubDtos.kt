package com.reviewer.infrastructure.git.dto

data class GitHubWebhookPayload(
    val action: String,
    val number: Int? = null,
    val pullRequest: GitHubPullRequest? = null,
    val repository: GitHubRepository? = null,
    val installation: GitHubInstallation? = null,
    val sender: GitHubUser? = null,
)

data class GitHubPullRequest(
    val id: Long,
    val number: Int,
    val title: String,
    val body: String? = null,
    val state: String,
    val draft: Boolean = false,
    val head: GitHubBranch,
    val base: GitHubBranch,
    val user: GitHubUser,
    val htmlUrl: String,
    val diffUrl: String,
)

data class GitHubBranch(
    val ref: String,
    val sha: String,
    val repo: GitHubBranchRepo? = null,
)

data class GitHubBranchRepo(
    val fullName: String,
)

data class GitHubRepository(
    val id: Long,
    val fullName: String,
    val name: String,
    val owner: GitHubUser,
    val private: Boolean = false,
)

data class GitHubUser(
    val login: String,
    val id: Long,
    val type: String? = null,
)

data class GitHubInstallation(
    val id: Long,
)

data class GitHubPrFile(
    val sha: String,
    val filename: String,
    val status: String,
    val additions: Int = 0,
    val deletions: Int = 0,
    val changes: Int = 0,
    val patch: String? = null,
)

data class GitHubCreateReviewRequest(
    val body: String,
    val event: String = "COMMENT",
    val comments: List<GitHubReviewComment> = emptyList(),
)

data class GitHubReviewComment(
    val path: String,
    val line: Int,
    val body: String,
    val side: String = "RIGHT",
)

data class GitHubAccessTokenResponse(
    val token: String,
    val expiresAt: String,
)

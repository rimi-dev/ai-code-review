package com.reviewer.infrastructure.git

import com.reviewer.infrastructure.git.dto.GitHubCreateReviewRequest
import com.reviewer.infrastructure.git.dto.GitHubPrFile
import io.github.oshai.kotlinlogging.KotlinLogging
import org.springframework.stereotype.Component
import org.springframework.web.reactive.function.client.WebClient
import org.springframework.web.reactive.function.client.awaitBody

private val logger = KotlinLogging.logger {}

@Component
class GitHubApiClient(
    private val webClientBuilder: WebClient.Builder,
    private val tokenProvider: GitHubAppTokenProvider,
) {
    private suspend fun createClient(installationId: Long): WebClient {
        val token = tokenProvider.getInstallationToken(installationId)
        return webClientBuilder
            .baseUrl("https://api.github.com")
            .defaultHeader("Authorization", "token $token")
            .defaultHeader("Accept", "application/vnd.github+json")
            .build()
    }

    suspend fun getPullRequestFiles(
        installationId: Long,
        owner: String,
        repo: String,
        prNumber: Int,
    ): List<GitHubPrFile> {
        val client = createClient(installationId)
        return client.get()
            .uri("/repos/$owner/$repo/pulls/$prNumber/files?per_page=100")
            .retrieve()
            .awaitBody()
    }

    suspend fun getPullRequestDiff(
        installationId: Long,
        owner: String,
        repo: String,
        prNumber: Int,
    ): String {
        val client = createClient(installationId)
        return client.get()
            .uri("/repos/$owner/$repo/pulls/$prNumber")
            .header("Accept", "application/vnd.github.v3.diff")
            .retrieve()
            .awaitBody()
    }

    suspend fun createPullRequestReview(
        installationId: Long,
        owner: String,
        repo: String,
        prNumber: Int,
        review: GitHubCreateReviewRequest,
    ) {
        val client = createClient(installationId)
        client.post()
            .uri("/repos/$owner/$repo/pulls/$prNumber/reviews")
            .bodyValue(review)
            .retrieve()
            .awaitBody<Any>()

        logger.info { "Posted review to $owner/$repo#$prNumber with ${review.comments.size} inline comments" }
    }
}

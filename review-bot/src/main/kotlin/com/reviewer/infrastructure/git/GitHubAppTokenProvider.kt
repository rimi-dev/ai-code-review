package com.reviewer.infrastructure.git

import com.reviewer.config.properties.GitHubProperties
import com.reviewer.infrastructure.git.dto.GitHubAccessTokenResponse
import io.github.oshai.kotlinlogging.KotlinLogging
import org.springframework.stereotype.Component
import org.springframework.web.reactive.function.client.WebClient
import org.springframework.web.reactive.function.client.awaitBody
import java.security.KeyFactory
import java.security.spec.PKCS8EncodedKeySpec
import java.time.Instant
import java.util.Base64
import java.util.concurrent.ConcurrentHashMap

private val logger = KotlinLogging.logger {}

@Component
class GitHubAppTokenProvider(
    private val gitHubProperties: GitHubProperties,
    private val webClientBuilder: WebClient.Builder,
) {
    private val tokenCache = ConcurrentHashMap<Long, CachedToken>()

    private data class CachedToken(val token: String, val expiresAt: Instant)

    suspend fun getInstallationToken(installationId: Long): String {
        val cached = tokenCache[installationId]
        if (cached != null && cached.expiresAt.isAfter(Instant.now().plusSeconds(60))) {
            return cached.token
        }

        val jwt = generateJwt()
        val webClient = webClientBuilder
            .baseUrl(gitHubProperties.apiBaseUrl)
            .defaultHeader("Authorization", "Bearer $jwt")
            .defaultHeader("Accept", "application/vnd.github+json")
            .build()

        val response = webClient.post()
            .uri("/app/installations/$installationId/access_tokens")
            .retrieve()
            .awaitBody<GitHubAccessTokenResponse>()

        val expiresAt = Instant.parse(response.expiresAt)
        tokenCache[installationId] = CachedToken(response.token, expiresAt)

        logger.debug { "Obtained installation token for installation $installationId" }
        return response.token
    }

    private fun generateJwt(): String {
        val now = Instant.now()
        val header = Base64.getUrlEncoder().withoutPadding()
            .encodeToString("""{"alg":"RS256","typ":"JWT"}""".toByteArray())
        val payload = Base64.getUrlEncoder().withoutPadding()
            .encodeToString(
                """{"iss":"${gitHubProperties.appId}","iat":${now.epochSecond - 60},"exp":${now.epochSecond + 600}}""".toByteArray(),
            )

        val signingInput = "$header.$payload"
        val privateKey = loadPrivateKey()
        val signature = java.security.Signature.getInstance("SHA256withRSA").apply {
            initSign(privateKey)
            update(signingInput.toByteArray())
        }.sign()

        val encodedSignature = Base64.getUrlEncoder().withoutPadding().encodeToString(signature)
        return "$header.$payload.$encodedSignature"
    }

    private fun loadPrivateKey(): java.security.PrivateKey {
        val keyContent = java.io.File(gitHubProperties.privateKeyPath).readText()
            .replace("-----BEGIN RSA PRIVATE KEY-----", "")
            .replace("-----END RSA PRIVATE KEY-----", "")
            .replace("-----BEGIN PRIVATE KEY-----", "")
            .replace("-----END PRIVATE KEY-----", "")
            .replace("\\s".toRegex(), "")

        val keyBytes = Base64.getDecoder().decode(keyContent)
        val keySpec = PKCS8EncodedKeySpec(keyBytes)
        return KeyFactory.getInstance("RSA").generatePrivate(keySpec)
    }
}

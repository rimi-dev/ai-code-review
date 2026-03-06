package com.reviewer.infrastructure.git

import com.reviewer.config.properties.GitHubProperties
import io.github.oshai.kotlinlogging.KotlinLogging
import org.springframework.stereotype.Component
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

private val logger = KotlinLogging.logger {}

@Component
class WebhookSignatureVerifier(
    private val gitHubProperties: GitHubProperties,
) {

    companion object {
        private const val HMAC_SHA256 = "HmacSHA256"
        private const val SIGNATURE_PREFIX = "sha256="
    }

    fun verify(payload: ByteArray, signature: String?): Boolean {
        if (signature.isNullOrBlank()) {
            logger.warn { "Missing webhook signature header" }
            return false
        }

        if (!signature.startsWith(SIGNATURE_PREFIX)) {
            logger.warn { "Invalid signature format: missing sha256= prefix" }
            return false
        }

        return try {
            val expectedSignature = computeHmac(payload)
            val actualSignature = signature.removePrefix(SIGNATURE_PREFIX)
            constantTimeEquals(expectedSignature, actualSignature)
        } catch (e: Exception) {
            logger.error(e) { "Failed to verify webhook signature" }
            false
        }
    }

    private fun computeHmac(payload: ByteArray): String {
        val secretKey = SecretKeySpec(
            gitHubProperties.webhookSecret.toByteArray(Charsets.UTF_8),
            HMAC_SHA256,
        )
        val mac = Mac.getInstance(HMAC_SHA256)
        mac.init(secretKey)
        val hash = mac.doFinal(payload)
        return hash.joinToString("") { "%02x".format(it) }
    }

    private fun constantTimeEquals(a: String, b: String): Boolean {
        if (a.length != b.length) return false
        var result = 0
        for (i in a.indices) {
            result = result or (a[i].code xor b[i].code)
        }
        return result == 0
    }
}

package com.reviewer.infrastructure.git

import com.reviewer.config.properties.GitHubProperties
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Nested
import org.junit.jupiter.api.Test
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

class WebhookSignatureVerifierTest {

    private lateinit var verifier: WebhookSignatureVerifier

    private val webhookSecret = "test-webhook-secret-key"

    private val gitHubProperties = GitHubProperties(
        webhookSecret = webhookSecret,
        appId = "12345",
        privateKeyPath = "/tmp/test-key.pem",
        apiBaseUrl = "https://api.github.com",
    )

    @BeforeEach
    fun setUp() {
        verifier = WebhookSignatureVerifier(gitHubProperties)
    }

    private fun computeExpectedSignature(payload: ByteArray): String {
        val secretKey = SecretKeySpec(webhookSecret.toByteArray(Charsets.UTF_8), "HmacSHA256")
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(secretKey)
        val hash = mac.doFinal(payload)
        return "sha256=" + hash.joinToString("") { "%02x".format(it) }
    }

    @Nested
    inner class ValidSignature {

        @Test
        fun `should return true for valid HMAC-SHA256 signature`() {
            val payload = """{"action":"opened","pull_request":{"number":1}}""".toByteArray()
            val signature = computeExpectedSignature(payload)

            val result = verifier.verify(payload, signature)

            assertTrue(result)
        }

        @Test
        fun `should return true for valid signature with different payload content`() {
            val payload = """{"key":"value","nested":{"deep":true}}""".toByteArray()
            val signature = computeExpectedSignature(payload)

            val result = verifier.verify(payload, signature)

            assertTrue(result)
        }

        @Test
        fun `should return true for empty payload with valid signature`() {
            val payload = "".toByteArray()
            val signature = computeExpectedSignature(payload)

            val result = verifier.verify(payload, signature)

            assertTrue(result)
        }
    }

    @Nested
    inner class InvalidSignature {

        @Test
        fun `should return false for tampered payload`() {
            val originalPayload = """{"action":"opened"}""".toByteArray()
            val signature = computeExpectedSignature(originalPayload)

            val tamperedPayload = """{"action":"closed"}""".toByteArray()

            val result = verifier.verify(tamperedPayload, signature)

            assertFalse(result)
        }

        @Test
        fun `should return false for incorrect signature value`() {
            val payload = """{"action":"opened"}""".toByteArray()
            val wrongSignature = "sha256=0000000000000000000000000000000000000000000000000000000000000000"

            val result = verifier.verify(payload, wrongSignature)

            assertFalse(result)
        }

        @Test
        fun `should return false for signature with wrong prefix`() {
            val payload = """{"action":"opened"}""".toByteArray()
            val signature = "sha1=abcdef1234567890"

            val result = verifier.verify(payload, signature)

            assertFalse(result)
        }

        @Test
        fun `should return false for signature without prefix`() {
            val payload = """{"action":"opened"}""".toByteArray()
            val signatureWithPrefix = computeExpectedSignature(payload)
            val signatureWithoutPrefix = signatureWithPrefix.removePrefix("sha256=")

            val result = verifier.verify(payload, signatureWithoutPrefix)

            assertFalse(result)
        }
    }

    @Nested
    inner class MissingSignature {

        @Test
        fun `should return false for null signature`() {
            val payload = """{"action":"opened"}""".toByteArray()

            val result = verifier.verify(payload, null)

            assertFalse(result)
        }

        @Test
        fun `should return false for empty string signature`() {
            val payload = """{"action":"opened"}""".toByteArray()

            val result = verifier.verify(payload, "")

            assertFalse(result)
        }

        @Test
        fun `should return false for blank signature`() {
            val payload = """{"action":"opened"}""".toByteArray()

            val result = verifier.verify(payload, "   ")

            assertFalse(result)
        }
    }

    @Nested
    inner class EmptyBody {

        @Test
        fun `should verify empty body with valid signature`() {
            val emptyPayload = ByteArray(0)
            val signature = computeExpectedSignature(emptyPayload)

            val result = verifier.verify(emptyPayload, signature)

            assertTrue(result)
        }

        @Test
        fun `should reject empty body with wrong signature`() {
            val emptyPayload = ByteArray(0)
            val wrongSignature = "sha256=ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"

            val result = verifier.verify(emptyPayload, wrongSignature)

            assertFalse(result)
        }
    }
}

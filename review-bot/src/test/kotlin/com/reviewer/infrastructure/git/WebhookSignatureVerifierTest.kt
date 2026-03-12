package com.reviewer.infrastructure.git

import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Nested
import org.junit.jupiter.api.Test
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

class WebhookSignatureVerifierTest {

    private lateinit var verifier: WebhookSignatureVerifier

    @BeforeEach
    fun setUp() {
        verifier = WebhookSignatureVerifier()
    }

    private fun computeHmacSha256(payload: ByteArray, secret: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(secret.toByteArray(), "HmacSHA256"))
        val hash = mac.doFinal(payload)
        return "sha256=" + hash.joinToString("") { "%02x".format(it) }
    }

    @Nested
    inner class ValidSignature {

        @Test
        fun `should return true for valid signature`() {
            val secret = "my-webhook-secret"
            val payload = """{"action":"opened","number":1}""".toByteArray()
            val signature = computeHmacSha256(payload, secret)

            val result = verifier.verify(payload, signature, secret)

            assertTrue(result)
        }

        @Test
        fun `should verify signature case-insensitively`() {
            val secret = "test-secret"
            val payload = "test payload".toByteArray()
            val signature = computeHmacSha256(payload, secret).uppercase()

            val result = verifier.verify(payload, signature, secret)

            assertTrue(result)
        }
    }

    @Nested
    inner class InvalidSignature {

        @Test
        fun `should return false for wrong signature`() {
            val secret = "my-webhook-secret"
            val payload = """{"action":"opened"}""".toByteArray()
            val wrongSignature = "sha256=0000000000000000000000000000000000000000000000000000000000000000"

            val result = verifier.verify(payload, wrongSignature, secret)

            assertFalse(result)
        }

        @Test
        fun `should return false for signature without sha256 prefix`() {
            val secret = "my-secret"
            val payload = "test".toByteArray()
            val signature = "invalid-signature-format"

            val result = verifier.verify(payload, signature, secret)

            assertFalse(result)
        }

        @Test
        fun `should return false when signature computed with different secret`() {
            val correctSecret = "correct-secret"
            val wrongSecret = "wrong-secret"
            val payload = "payload data".toByteArray()
            val signature = computeHmacSha256(payload, wrongSecret)

            val result = verifier.verify(payload, signature, correctSecret)

            assertFalse(result)
        }

        @Test
        fun `should return false when payload is tampered`() {
            val secret = "my-secret"
            val originalPayload = "original data".toByteArray()
            val signature = computeHmacSha256(originalPayload, secret)
            val tamperedPayload = "tampered data".toByteArray()

            val result = verifier.verify(tamperedPayload, signature, secret)

            assertFalse(result)
        }
    }

    @Nested
    inner class BlankSecret {

        @Test
        fun `should return true when secret is blank`() {
            val payload = "any payload".toByteArray()
            val signature = "any-signature"

            val result = verifier.verify(payload, signature, "")

            assertTrue(result)
        }

        @Test
        fun `should return true when secret is whitespace`() {
            val payload = "any payload".toByteArray()
            val signature = "any-signature"

            val result = verifier.verify(payload, signature, "   ")

            assertTrue(result)
        }
    }

    @Nested
    inner class EmptyPayload {

        @Test
        fun `should verify empty payload with valid signature`() {
            val secret = "my-secret"
            val payload = ByteArray(0)
            val signature = computeHmacSha256(payload, secret)

            val result = verifier.verify(payload, signature, secret)

            assertTrue(result)
        }

        @Test
        fun `should reject empty payload with wrong signature`() {
            val secret = "my-secret"
            val payload = ByteArray(0)
            val wrongSignature = "sha256=0000000000000000000000000000000000000000000000000000000000000000"

            val result = verifier.verify(payload, wrongSignature, secret)

            assertFalse(result)
        }
    }
}

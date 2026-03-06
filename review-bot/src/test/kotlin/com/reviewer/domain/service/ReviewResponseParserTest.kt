package com.reviewer.domain.service

import com.reviewer.domain.model.Severity
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Nested
import org.junit.jupiter.api.Test
import tools.jackson.databind.DeserializationFeature
import tools.jackson.databind.ObjectMapper
import tools.jackson.databind.json.JsonMapper

class ReviewResponseParserTest {

    private lateinit var parser: ReviewResponseParser
    private lateinit var objectMapper: ObjectMapper

    @BeforeEach
    fun setUp() {
        objectMapper = JsonMapper.builder()
            .findAndAddModules()
            .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .build()
        parser = ReviewResponseParser(objectMapper)
    }

    private fun parse(response: String) = parser.parse(
        llmResponse = response,
        reviewRequestId = "req-123",
        repositoryFullName = "owner/repo",
        pullRequestNumber = 42,
    )

    @Nested
    inner class ValidJsonParsing {

        @Test
        fun `should parse valid JSON response with comments array`() {
            val response = """
                [
                  {
                    "file": "src/Main.kt",
                    "line": 10,
                    "severity": "WARNING",
                    "category": "quality",
                    "title": "Unused import",
                    "body": "This import is not used anywhere in the file.",
                    "suggestion": null
                  },
                  {
                    "file": "src/Service.kt",
                    "line": 25,
                    "severity": "CRITICAL",
                    "category": "bug",
                    "title": "Null pointer risk",
                    "body": "This value can be null but is not handled.",
                    "suggestion": "val value = data ?: return"
                  }
                ]
            """.trimIndent()

            val result = parse(response)

            assertEquals(2, result.size)

            assertEquals("src/Main.kt", result[0].filePath)
            assertEquals(10, result[0].line)
            assertEquals(Severity.WARNING, result[0].severity)
            assertEquals("quality", result[0].category)
            assertEquals("Unused import", result[0].title)
            assertEquals("req-123", result[0].reviewRequestId)
            assertEquals("owner/repo", result[0].repositoryFullName)
            assertEquals(42, result[0].pullRequestNumber)

            assertEquals("src/Service.kt", result[1].filePath)
            assertEquals(25, result[1].line)
            assertEquals(Severity.CRITICAL, result[1].severity)
            assertEquals("bug", result[1].category)
            assertEquals("val value = data ?: return", result[1].suggestion)
        }

        @Test
        fun `should parse markdown-wrapped JSON response`() {
            val response = """
                Here are my review comments:
                
                ```json
                [
                  {
                    "file": "src/App.kt",
                    "line": 5,
                    "severity": "SUGGESTION",
                    "category": "best-practice",
                    "title": "Consider using lazy initialization",
                    "body": "This logger could be lazily initialized."
                  }
                ]
                ```
                
                Let me know if you need more details.
            """.trimIndent()

            val result = parse(response)

            assertEquals(1, result.size)
            assertEquals("src/App.kt", result[0].filePath)
            assertEquals(Severity.SUGGESTION, result[0].severity)
            assertEquals("best-practice", result[0].category)
        }

        @Test
        fun `should parse markdown code block without json language tag`() {
            val response = """
                ```
                [
                  {
                    "file": "src/Util.kt",
                    "line": 3,
                    "severity": "PRAISE",
                    "category": "quality",
                    "title": "Clean implementation",
                    "body": "Well-structured code."
                  }
                ]
                ```
            """.trimIndent()

            val result = parse(response)

            assertEquals(1, result.size)
            assertEquals(Severity.PRAISE, result[0].severity)
        }
    }

    @Nested
    inner class GracefulHandling {

        @Test
        fun `should handle missing optional fields gracefully`() {
            val response = """
                [
                  {
                    "file": "src/Main.kt",
                    "line": null,
                    "severity": "SUGGESTION",
                    "category": "quality",
                    "title": "General observation",
                    "body": "Consider adding more documentation."
                  }
                ]
            """.trimIndent()

            val result = parse(response)

            assertEquals(1, result.size)
            assertNull(result[0].line)
            assertNull(result[0].suggestion)
        }

        @Test
        fun `should return empty list for empty response`() {
            val result = parse("")

            assertTrue(result.isEmpty())
        }

        @Test
        fun `should return empty list for response with no JSON`() {
            val result = parse("This PR looks good overall. No issues found.")

            assertTrue(result.isEmpty())
        }

        @Test
        fun `should return empty list for malformed JSON`() {
            val response = """
                [
                  { "file": "src/Main.kt", "line": 10, "severity": "WARNING"
                  // this is malformed
                ]
            """.trimIndent()

            val result = parse(response)

            assertTrue(result.isEmpty())
        }

        @Test
        fun `should handle empty JSON array`() {
            val response = "[]"

            val result = parse(response)

            assertTrue(result.isEmpty())
        }

        @Test
        fun `should handle response with only empty array text`() {
            val response = "No issues found. Returning empty result: []"

            val result = parse(response)

            assertTrue(result.isEmpty())
        }
    }

    @Nested
    inner class SeverityMapping {

        @Test
        fun `should map CRITICAL severity`() {
            val response = buildSingleCommentResponse(severity = "CRITICAL")

            val result = parse(response)

            assertEquals(1, result.size)
            assertEquals(Severity.CRITICAL, result[0].severity)
        }

        @Test
        fun `should map WARNING severity`() {
            val response = buildSingleCommentResponse(severity = "WARNING")

            val result = parse(response)

            assertEquals(Severity.WARNING, result[0].severity)
        }

        @Test
        fun `should map SUGGESTION severity`() {
            val response = buildSingleCommentResponse(severity = "SUGGESTION")

            val result = parse(response)

            assertEquals(Severity.SUGGESTION, result[0].severity)
        }

        @Test
        fun `should map PRAISE severity`() {
            val response = buildSingleCommentResponse(severity = "PRAISE")

            val result = parse(response)

            assertEquals(Severity.PRAISE, result[0].severity)
        }

        @Test
        fun `should default to SUGGESTION for unknown severity`() {
            val response = buildSingleCommentResponse(severity = "info")

            val result = parse(response)

            assertEquals(Severity.SUGGESTION, result[0].severity)
        }

        @Test
        fun `should handle lowercase severity by mapping to uppercase`() {
            val response = buildSingleCommentResponse(severity = "warning")

            val result = parse(response)

            assertEquals(Severity.WARNING, result[0].severity)
        }
    }

    @Nested
    inner class CategoryExtraction {

        @Test
        fun `should extract bug category`() {
            val response = buildSingleCommentResponse(category = "bug")

            val result = parse(response)

            assertEquals("bug", result[0].category)
        }

        @Test
        fun `should extract security category`() {
            val response = buildSingleCommentResponse(category = "security")

            val result = parse(response)

            assertEquals("security", result[0].category)
        }

        @Test
        fun `should extract performance category`() {
            val response = buildSingleCommentResponse(category = "performance")

            val result = parse(response)

            assertEquals("performance", result[0].category)
        }

        @Test
        fun `should extract quality category`() {
            val response = buildSingleCommentResponse(category = "quality")

            val result = parse(response)

            assertEquals("quality", result[0].category)
        }

        @Test
        fun `should extract best-practice category`() {
            val response = buildSingleCommentResponse(category = "best-practice")

            val result = parse(response)

            assertEquals("best-practice", result[0].category)
        }
    }

    private fun buildSingleCommentResponse(
        severity: String = "WARNING",
        category: String = "quality",
    ): String = """
        [
          {
            "file": "src/Test.kt",
            "line": 1,
            "severity": "$severity",
            "category": "$category",
            "title": "Test comment",
            "body": "Test body"
          }
        ]
    """.trimIndent()
}

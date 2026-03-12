package com.reviewer.domain.service

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Nested
import org.junit.jupiter.api.Test

class ReviewResponseParserTest {

    private lateinit var parser: ReviewResponseParser

    @BeforeEach
    fun setUp() {
        parser = ReviewResponseParser()
    }

    @Nested
    inner class JsonCodeBlockParsing {

        @Test
        fun `should parse JSON wrapped in code block with json language tag`() {
            val llmResponse = """
                Here are my review comments:
                ```json
                [
                    {
                        "file": "src/App.kt",
                        "line": 10,
                        "severity": "WARNING",
                        "category": "quality",
                        "title": "Null safety issue",
                        "body": "This variable could be null",
                        "suggestion": "val x = value ?: default"
                    }
                ]
                ```
            """.trimIndent()

            val result = parser.parse(llmResponse)

            assertEquals(1, result.size)
            assertEquals("src/App.kt", result[0].filePath)
            assertEquals(10, result[0].lineNumber)
            assertEquals("WARNING", result[0].severity)
            assertEquals("quality", result[0].category)
            assertTrue(result[0].content.contains("Null safety issue"))
            assertTrue(result[0].content.contains("This variable could be null"))
            assertEquals("val x = value ?: default", result[0].suggestion)
        }

        @Test
        fun `should parse JSON wrapped in code block without language tag`() {
            val llmResponse = """
                ```
                [
                    {
                        "file": "src/Service.kt",
                        "line": 5,
                        "severity": "CRITICAL",
                        "category": "security",
                        "title": "SQL Injection",
                        "body": "Use parameterized queries"
                    }
                ]
                ```
            """.trimIndent()

            val result = parser.parse(llmResponse)

            assertEquals(1, result.size)
            assertEquals("src/Service.kt", result[0].filePath)
            assertEquals("CRITICAL", result[0].severity)
            assertEquals("security", result[0].category)
        }

        @Test
        fun `should parse multiple comments from code block`() {
            val llmResponse = """
                ```json
                [
                    {
                        "file": "src/A.kt",
                        "line": 1,
                        "severity": "WARNING",
                        "category": "bug",
                        "title": "Bug A",
                        "body": "Description A"
                    },
                    {
                        "file": "src/B.kt",
                        "line": 2,
                        "severity": "SUGGESTION",
                        "category": "style",
                        "title": "Style B",
                        "body": "Description B"
                    }
                ]
                ```
            """.trimIndent()

            val result = parser.parse(llmResponse)

            assertEquals(2, result.size)
            assertEquals("src/A.kt", result[0].filePath)
            assertEquals("src/B.kt", result[1].filePath)
        }
    }

    @Nested
    inner class BareJsonParsing {

        @Test
        fun `should parse bare JSON array without code block`() {
            val llmResponse = """
                [
                    {
                        "file": "src/Handler.kt",
                        "line": 42,
                        "severity": "SUGGESTION",
                        "category": "performance",
                        "title": "Use lazy evaluation",
                        "body": "Consider using sequence instead of list"
                    }
                ]
            """.trimIndent()

            val result = parser.parse(llmResponse)

            assertEquals(1, result.size)
            assertEquals("src/Handler.kt", result[0].filePath)
            assertEquals(42, result[0].lineNumber)
            assertEquals("SUGGESTION", result[0].severity)
            assertEquals("performance", result[0].category)
        }

        @Test
        fun `should parse bare JSON with surrounding text`() {
            val llmResponse = """
                Based on my analysis, here are the issues:

                [
                    {
                        "file": "src/Config.kt",
                        "line": 7,
                        "severity": "WARNING",
                        "category": "best-practice",
                        "title": "Hardcoded value",
                        "body": "Extract to configuration"
                    }
                ]

                Please review the above comments.
            """.trimIndent()

            val result = parser.parse(llmResponse)

            assertEquals(1, result.size)
            assertEquals("src/Config.kt", result[0].filePath)
        }
    }

    @Nested
    inner class InvalidJsonHandling {

        @Test
        fun `should return empty list for invalid JSON`() {
            val llmResponse = "This is not valid JSON at all"

            val result = parser.parse(llmResponse)

            assertTrue(result.isEmpty())
        }

        @Test
        fun `should return empty list for malformed JSON array`() {
            val llmResponse = """
                [
                    { "file": "src/App.kt", "line": INVALID }
                ]
            """.trimIndent()

            val result = parser.parse(llmResponse)

            assertTrue(result.isEmpty())
        }

        @Test
        fun `should return empty list for JSON object instead of array`() {
            val llmResponse = """
                { "file": "src/App.kt", "line": 10 }
            """.trimIndent()

            val result = parser.parse(llmResponse)

            assertTrue(result.isEmpty())
        }
    }

    @Nested
    inner class EmptyResponse {

        @Test
        fun `should return empty list for empty string`() {
            val result = parser.parse("")

            assertTrue(result.isEmpty())
        }

        @Test
        fun `should return empty list for empty JSON array`() {
            val result = parser.parse("[]")

            assertTrue(result.isEmpty())
        }

        @Test
        fun `should return empty list for blank string`() {
            val result = parser.parse("   \n   ")

            assertTrue(result.isEmpty())
        }
    }

    @Nested
    inner class SeverityNormalization {

        @Test
        fun `should normalize known severity values`() {
            val llmResponse = """
                [
                    {"file":"a.kt","line":1,"severity":"CRITICAL","category":"bug","title":"T","body":"B"},
                    {"file":"b.kt","line":2,"severity":"WARNING","category":"bug","title":"T","body":"B"},
                    {"file":"c.kt","line":3,"severity":"SUGGESTION","category":"bug","title":"T","body":"B"},
                    {"file":"d.kt","line":4,"severity":"PRAISE","category":"bug","title":"T","body":"B"}
                ]
            """.trimIndent()

            val result = parser.parse(llmResponse)

            assertEquals("CRITICAL", result[0].severity)
            assertEquals("WARNING", result[1].severity)
            assertEquals("SUGGESTION", result[2].severity)
            assertEquals("PRAISE", result[3].severity)
        }

        @Test
        fun `should normalize INFO severity to SUGGESTION`() {
            val llmResponse = """
                [
                    {"file":"a.kt","line":1,"severity":"INFO","category":"quality","title":"T","body":"B"}
                ]
            """.trimIndent()

            val result = parser.parse(llmResponse)

            assertEquals("SUGGESTION", result[0].severity)
        }

        @Test
        fun `should normalize unknown severity to SUGGESTION`() {
            val llmResponse = """
                [
                    {"file":"a.kt","line":1,"severity":"UNKNOWN","category":"quality","title":"T","body":"B"}
                ]
            """.trimIndent()

            val result = parser.parse(llmResponse)

            assertEquals("SUGGESTION", result[0].severity)
        }
    }

    @Nested
    inner class ContentFormatting {

        @Test
        fun `should format content as title followed by body`() {
            val llmResponse = """
                [
                    {
                        "file": "src/App.kt",
                        "line": 1,
                        "severity": "WARNING",
                        "category": "quality",
                        "title": "Missing validation",
                        "body": "Input should be validated before processing"
                    }
                ]
            """.trimIndent()

            val result = parser.parse(llmResponse)

            assertEquals("Missing validation\n\nInput should be validated before processing", result[0].content)
        }

        @Test
        fun `should lowercase category`() {
            val llmResponse = """
                [
                    {"file":"a.kt","line":1,"severity":"WARNING","category":"QUALITY","title":"T","body":"B"}
                ]
            """.trimIndent()

            val result = parser.parse(llmResponse)

            assertEquals("quality", result[0].category)
        }
    }

    @Nested
    inner class SnakeCaseMapping {

        @Test
        fun `should handle unknown fields gracefully`() {
            val llmResponse = """
                [
                    {
                        "file": "src/App.kt",
                        "line": 1,
                        "severity": "WARNING",
                        "category": "quality",
                        "title": "Title",
                        "body": "Body",
                        "extra_field": "should be ignored"
                    }
                ]
            """.trimIndent()

            val result = parser.parse(llmResponse)

            assertEquals(1, result.size)
            assertEquals("src/App.kt", result[0].filePath)
        }
    }
}

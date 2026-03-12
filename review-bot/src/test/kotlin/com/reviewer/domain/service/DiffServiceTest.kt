package com.reviewer.domain.service

import com.reviewer.config.properties.ReviewProperties
import com.reviewer.domain.service.DiffService.LineType
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Nested
import org.junit.jupiter.api.Test

class DiffServiceTest {

    private lateinit var diffService: DiffService

    @BeforeEach
    fun setUp() {
        val reviewProperties = ReviewProperties(
            maxDiffLines = 3000,
            maxFiles = 50,
            contextLines = 5,
            excludePatterns = listOf("*.lock", "*.min.js"),
        )
        diffService = DiffService(reviewProperties)
    }

    @Nested
    inner class ParseSingleFileDiff {

        @Test
        fun `should parse single file diff with additions and deletions`() {
            val rawDiff = """
                diff --git a/src/main/kotlin/App.kt b/src/main/kotlin/App.kt
                --- a/src/main/kotlin/App.kt
                +++ b/src/main/kotlin/App.kt
                @@ -1,5 +1,6 @@
                 package com.example

                -fun oldFunction() {
                +fun newFunction() {
                +    println("hello")
                 }
            """.trimIndent()

            val result = diffService.parseDiff(rawDiff)

            assertEquals(1, result.size)
            assertEquals("src/main/kotlin/App.kt", result[0].filePath)
            assertEquals(1, result[0].hunks.size)

            val hunk = result[0].hunks[0]
            val addedLines = hunk.lines.filter { it.type == LineType.ADDED }
            val removedLines = hunk.lines.filter { it.type == LineType.REMOVED }

            assertEquals(2, addedLines.size)
            assertEquals(1, removedLines.size)
            assertEquals(2, result[0].additions)
            assertEquals(1, result[0].deletions)
        }

        @Test
        fun `should extract correct new start line number from hunk header`() {
            val rawDiff = """
                diff --git a/src/Service.kt b/src/Service.kt
                --- a/src/Service.kt
                +++ b/src/Service.kt
                @@ -10,3 +15,4 @@
                 context line
                +added line
                 another context
            """.trimIndent()

            val result = diffService.parseDiff(rawDiff)

            assertEquals(1, result.size)
            val hunk = result[0].hunks[0]
            assertEquals(15, hunk.newStartLine)
        }
    }

    @Nested
    inner class ParseMultiFileDiff {

        @Test
        fun `should parse diff with multiple files`() {
            val rawDiff = """
                diff --git a/src/FileA.kt b/src/FileA.kt
                --- a/src/FileA.kt
                +++ b/src/FileA.kt
                @@ -1,3 +1,4 @@
                 line1
                +added in A
                 line2
                diff --git a/src/FileB.kt b/src/FileB.kt
                --- a/src/FileB.kt
                +++ b/src/FileB.kt
                @@ -1,2 +1,3 @@
                 line1
                +added in B
                 line2
            """.trimIndent()

            val result = diffService.parseDiff(rawDiff)

            assertEquals(2, result.size)
            assertEquals("src/FileA.kt", result[0].filePath)
            assertEquals("src/FileB.kt", result[1].filePath)
        }
    }

    @Nested
    inner class ParseRenameDiff {

        @Test
        fun `should parse renamed file diff`() {
            val rawDiff = """
                diff --git a/src/OldName.kt b/src/NewName.kt
                similarity index 90%
                rename from src/OldName.kt
                rename to src/NewName.kt
                --- a/src/OldName.kt
                +++ b/src/NewName.kt
                @@ -1,3 +1,3 @@
                 package com.example

                -class OldName
                +class NewName
            """.trimIndent()

            val result = diffService.parseDiff(rawDiff)

            assertEquals(1, result.size)
            assertEquals("src/NewName.kt", result[0].filePath)
            assertEquals(1, result[0].additions)
            assertEquals(1, result[0].deletions)
        }
    }

    @Nested
    inner class BinaryFileDiff {

        @Test
        fun `should skip binary file diff without +++ b line`() {
            val rawDiff = """
                diff --git a/image.png b/image.png
                Binary files /dev/null and b/image.png differ
            """.trimIndent()

            val result = diffService.parseDiff(rawDiff)

            assertTrue(result.isEmpty())
        }

        @Test
        fun `should skip binary file that has no hunk header`() {
            val rawDiff = """
                diff --git a/assets/logo.png b/assets/logo.png
                index abc1234..def5678 100644
                Binary files a/assets/logo.png and b/assets/logo.png differ
            """.trimIndent()

            val result = diffService.parseDiff(rawDiff)

            assertTrue(result.isEmpty())
        }
    }

    @Nested
    inner class EmptyDiff {

        @Test
        fun `should return empty list for empty diff string`() {
            val result = diffService.parseDiff("")

            assertTrue(result.isEmpty())
        }

        @Test
        fun `should return empty list for blank diff string`() {
            val result = diffService.parseDiff("   \n   \n")

            assertTrue(result.isEmpty())
        }
    }

    @Nested
    inner class ExcludePatterns {

        @Test
        fun `should exclude files matching exclude patterns`() {
            val rawDiff = """
                diff --git a/package-lock.json b/package-lock.json
                --- a/package-lock.json
                +++ b/package-lock.json
                @@ -1,2 +1,2 @@
                -old lock content
                +new lock content
            """.trimIndent()

            // .lock pattern won't match package-lock.json, but let's test with a matching pattern
            assertTrue(diffService.shouldExclude("yarn.lock"))
            assertTrue(diffService.shouldExclude("lib/bundle.min.js"))
        }

        @Test
        fun `should not exclude files not matching patterns`() {
            assertTrue(!diffService.shouldExclude("src/main/App.kt"))
            assertTrue(!diffService.shouldExclude("build.gradle.kts"))
        }
    }

    @Nested
    inner class MultipleHunks {

        @Test
        fun `should parse diff with multiple hunks in same file`() {
            val rawDiff = """
                diff --git a/src/Service.kt b/src/Service.kt
                --- a/src/Service.kt
                +++ b/src/Service.kt
                @@ -1,3 +1,4 @@
                 package com.example

                +import java.util.List
                 class Service {
                @@ -10,3 +11,4 @@
                     fun doWork() {
                +        println("working")
                     }
            """.trimIndent()

            val result = diffService.parseDiff(rawDiff)

            assertEquals(1, result.size)
            assertEquals(2, result[0].hunks.size)
            assertEquals(1, result[0].hunks[0].newStartLine)
            assertEquals(11, result[0].hunks[1].newStartLine)
        }
    }

    @Nested
    inner class MaxFilesLimit {

        @Test
        fun `should limit files to maxFiles property`() {
            val properties = ReviewProperties(
                maxFiles = 2,
                excludePatterns = emptyList(),
            )
            val service = DiffService(properties)

            val rawDiff = buildString {
                for (i in 1..5) {
                    appendLine("diff --git a/file$i.kt b/file$i.kt")
                    appendLine("--- a/file$i.kt")
                    appendLine("+++ b/file$i.kt")
                    appendLine("@@ -1,2 +1,3 @@")
                    appendLine(" context")
                    appendLine("+added line $i")
                    appendLine(" more context")
                }
            }

            val result = service.parseDiff(rawDiff)

            assertEquals(2, result.size)
        }
    }

    @Nested
    inner class BuildDiffContext {

        @Test
        fun `should format diff context with correct prefixes`() {
            val fileDiff = DiffService.FileDiff(
                filePath = "src/App.kt",
                hunks = listOf(
                    DiffService.DiffHunk(
                        header = "@@ -1,3 +1,4 @@",
                        newStartLine = 1,
                        lines = listOf(
                            DiffService.DiffLine("context line", LineType.CONTEXT, 1),
                            DiffService.DiffLine("added line", LineType.ADDED, 2),
                            DiffService.DiffLine("removed line", LineType.REMOVED, null),
                        ),
                    ),
                ),
                additions = 1,
                deletions = 1,
            )

            val result = diffService.buildDiffContext(fileDiff)

            assertTrue(result.contains("@@ -1,3 +1,4 @@"))
            assertTrue(result.contains(" context line"))
            assertTrue(result.contains("+added line"))
            assertTrue(result.contains("-removed line"))
        }
    }
}

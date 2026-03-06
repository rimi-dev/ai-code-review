package com.reviewer.domain.service

import com.reviewer.config.properties.ReviewProperties
import com.reviewer.infrastructure.git.dto.PrFile
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Nested
import org.junit.jupiter.api.Test

class DiffServiceTest {

    private lateinit var diffService: DiffService

    private val defaultReviewProperties = ReviewProperties(
        maxDiffLines = 3000,
        maxFiles = 50,
        excludePatterns = listOf(
            "*.lock",
            "*.min.js",
            "*.min.css",
            "*.map",
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "go.sum",
            "*.pb.go",
            "*.generated.*",
        ),
    )

    @BeforeEach
    fun setUp() {
        diffService = DiffService(defaultReviewProperties)
    }

    @Nested
    inner class ParseDiff {

        @Test
        fun `should parse a simple unified diff with one file`() {
            val rawDiff = """
                |diff --git a/src/Main.kt b/src/Main.kt
                |index 1234567..abcdefg 100644
                |--- a/src/Main.kt
                |+++ b/src/Main.kt
                |@@ -1,5 +1,6 @@
                | package com.example
                | 
                | fun main() {
                |-    println("Hello")
                |+    println("Hello, World!")
                |+    println("Welcome")
                | }
            """.trimMargin()

            val result = diffService.parseDiff(rawDiff)

            assertEquals(1, result.files.size)
            assertEquals("src/Main.kt", result.files[0].path)
            assertEquals(1, result.files[0].hunks.size)
            assertEquals(2, result.files[0].additions)
            assertEquals(1, result.files[0].deletions)
            assertFalse(result.truncated)
        }

        @Test
        fun `should parse multi-file diff`() {
            val rawDiff = """
                |diff --git a/src/Foo.kt b/src/Foo.kt
                |index 1111111..2222222 100644
                |--- a/src/Foo.kt
                |+++ b/src/Foo.kt
                |@@ -1,3 +1,4 @@
                | package com.example
                | 
                |+import org.slf4j.Logger
                | class Foo
                |diff --git a/src/Bar.kt b/src/Bar.kt
                |index 3333333..4444444 100644
                |--- a/src/Bar.kt
                |+++ b/src/Bar.kt
                |@@ -1,3 +1,3 @@
                | package com.example
                | 
                |-class Bar
                |+class Bar(val name: String)
            """.trimMargin()

            val result = diffService.parseDiff(rawDiff)

            assertEquals(2, result.files.size)
            assertEquals("src/Foo.kt", result.files[0].path)
            assertEquals("src/Bar.kt", result.files[1].path)
            assertEquals(1, result.files[0].additions)
            assertEquals(0, result.files[0].deletions)
            assertEquals(1, result.files[1].additions)
            assertEquals(1, result.files[1].deletions)
        }

        @Test
        fun `should parse empty diff`() {
            val rawDiff = ""

            val result = diffService.parseDiff(rawDiff)

            assertEquals(0, result.files.size)
            assertEquals(0, result.totalLines)
            assertFalse(result.truncated)
        }

        @Test
        fun `should detect binary file diff sections gracefully`() {
            val rawDiff = """
                |diff --git a/image.png b/image.png
                |new file mode 100644
                |index 0000000..abcdefg
                |Binary files /dev/null and b/image.png differ
                |diff --git a/src/App.kt b/src/App.kt
                |index 1234567..abcdefg 100644
                |--- a/src/App.kt
                |+++ b/src/App.kt
                |@@ -1,3 +1,4 @@
                | package com.example
                | 
                |+import java.io.File
                | class App
            """.trimMargin()

            val result = diffService.parseDiff(rawDiff)

            // Binary file has no hunks
            val binaryFile = result.files.find { it.path == "image.png" }
            val sourceFile = result.files.find { it.path == "src/App.kt" }

            // Binary file detected but has no parseable hunks
            if (binaryFile != null) {
                assertEquals(0, binaryFile.hunks.size)
            }

            // Source file still parsed correctly
            assertNotNull(sourceFile)
            assertEquals(1, sourceFile!!.additions)
        }

        @Test
        fun `should detect rename in diff`() {
            val rawDiff = """
                |diff --git a/src/OldName.kt b/src/NewName.kt
                |similarity index 95%
                |rename from src/OldName.kt
                |rename to src/NewName.kt
                |index 1234567..abcdefg 100644
                |--- a/src/OldName.kt
                |+++ b/src/NewName.kt
                |@@ -1,3 +1,3 @@
                | package com.example
                | 
                |-class OldName
                |+class NewName
            """.trimMargin()

            val result = diffService.parseDiff(rawDiff)

            assertEquals(1, result.files.size)
            // The parser extracts the "b/" path (destination)
            assertEquals("src/NewName.kt", result.files[0].path)
            assertEquals(1, result.files[0].additions)
            assertEquals(1, result.files[0].deletions)
        }

        @Test
        fun `should track line numbers correctly in diff context`() {
            val rawDiff = """
                |diff --git a/src/Service.kt b/src/Service.kt
                |index 1234567..abcdefg 100644
                |--- a/src/Service.kt
                |+++ b/src/Service.kt
                |@@ -10,7 +10,8 @@
                |     fun process() {
                |         val data = fetchData()
                |-        transform(data)
                |+        val result = transform(data)
                |+        log(result)
                |         save(data)
                |     }
            """.trimMargin()

            val result = diffService.parseDiff(rawDiff)

            assertEquals(1, result.files.size)
            val hunk = result.files[0].hunks[0]
            assertEquals(10, hunk.startLineOld)
            assertEquals(10, hunk.startLineNew)

            // Check line numbers: context starts at line 10
            val lines = hunk.lines
            // "    fun process() {" -> context at old=10, new=10
            val contextLine = lines.first { it.type == DiffService.LineType.CONTEXT }
            assertEquals(10, contextLine.oldLineNumber)
            assertEquals(10, contextLine.newLineNumber)

            // The deletion "        transform(data)" -> old line 12
            val deletionLine = lines.first { it.type == DiffService.LineType.DELETION }
            assertEquals(12, deletionLine.oldLineNumber)
            assertNull(deletionLine.newLineNumber)

            // First addition "        val result = transform(data)" -> new line 12
            val additionLines = lines.filter { it.type == DiffService.LineType.ADDITION }
            assertEquals(2, additionLines.size)
            assertEquals(12, additionLines[0].newLineNumber)
            assertEquals(13, additionLines[1].newLineNumber)
        }

        @Test
        fun `should truncate diff when exceeding maxDiffLines`() {
            val smallLimitProperties = ReviewProperties(
                maxDiffLines = 5,
                maxFiles = 50,
                excludePatterns = emptyList(),
            )
            val service = DiffService(smallLimitProperties)

            val rawDiff = """
                |diff --git a/src/Big.kt b/src/Big.kt
                |index 1234567..abcdefg 100644
                |--- a/src/Big.kt
                |+++ b/src/Big.kt
                |@@ -1,3 +1,10 @@
                | line1
                | line2
                | line3
                |+added1
                |+added2
                |+added3
                |+added4
                |+added5
                |+added6
                |+added7
            """.trimMargin()

            val result = service.parseDiff(rawDiff)

            assertTrue(result.truncated)
            // totalLines is at most maxDiffLines + 1 (incremented before the truncation check)
            assertTrue(result.totalLines <= 6)
            assertTrue(result.totalLines < 10, "Should have stopped well before processing all 10 lines")
        }

        @Test
        fun `should parse diff from fixture file`() {
            val fixtureDiff = this::class.java.classLoader
                .getResource("fixtures/sample-diff.txt")!!
                .readText()

            val result = diffService.parseDiff(fixtureDiff)

            assertEquals(3, result.files.size)
            assertEquals("src/main/kotlin/com/example/UserService.kt", result.files[0].path)
            assertEquals("src/main/kotlin/com/example/EmailService.kt", result.files[1].path)
            assertEquals("build.gradle.kts", result.files[2].path)
            assertFalse(result.truncated)

            // UserService.kt has additions and deletions
            assertTrue(result.files[0].additions > 0)
            assertTrue(result.files[0].deletions > 0)

            // EmailService.kt is a new file, all additions
            assertTrue(result.files[1].additions > 0)
            assertEquals(0, result.files[1].deletions)
        }
    }

    @Nested
    inner class FilterFiles {

        @Test
        fun `should exclude files matching lock patterns`() {
            val files = listOf(
                createPrFile("package-lock.json"),
                createPrFile("yarn.lock"),
                createPrFile("src/main/App.kt"),
                createPrFile("pnpm-lock.yaml"),
            )

            val result = diffService.filterFiles(files, emptyList())

            assertEquals(1, result.size)
            assertEquals("src/main/App.kt", result[0].filename)
        }

        @Test
        fun `should exclude minified JS files`() {
            val files = listOf(
                createPrFile("dist/bundle.min.js"),
                createPrFile("src/index.ts"),
                createPrFile("assets/style.min.css"),
            )

            val result = diffService.filterFiles(files, emptyList())

            assertEquals(1, result.size)
            assertEquals("src/index.ts", result[0].filename)
        }

        @Test
        fun `should exclude files matching custom exclude patterns`() {
            val files = listOf(
                createPrFile("src/main/App.kt"),
                createPrFile("src/test/AppTest.kt"),
                createPrFile("docs/README.md"),
            )

            val result = diffService.filterFiles(files, listOf("docs/*", "*Test.kt"))

            assertEquals(1, result.size)
            assertEquals("src/main/App.kt", result[0].filename)
        }

        @Test
        fun `should exclude node_modules via glob pattern`() {
            val files = listOf(
                createPrFile("node_modules/lodash/index.js"),
                createPrFile("src/app.ts"),
            )

            val result = diffService.filterFiles(files, listOf("node_modules/*"))

            assertEquals(1, result.size)
            assertEquals("src/app.ts", result[0].filename)
        }

        @Test
        fun `should respect maxFiles limit`() {
            val files = (1..100).map { createPrFile("src/File$it.kt") }

            val result = diffService.filterFiles(files, emptyList())

            assertEquals(50, result.size) // maxFiles default is 50
        }

        @Test
        fun `should exclude generated files`() {
            val files = listOf(
                createPrFile("src/api.generated.ts"),
                createPrFile("proto/message.pb.go"),
                createPrFile("src/main/App.kt"),
            )

            val result = diffService.filterFiles(files, emptyList())

            assertEquals(1, result.size)
            assertEquals("src/main/App.kt", result[0].filename)
        }
    }

    @Nested
    inner class BuildFilteredDiff {

        @Test
        fun `should include only allowed files in filtered diff`() {
            val rawDiff = """
                |diff --git a/src/Foo.kt b/src/Foo.kt
                |index 1111111..2222222 100644
                |--- a/src/Foo.kt
                |+++ b/src/Foo.kt
                |@@ -1,3 +1,4 @@
                | package com.example
                |+import java.io.File
                | class Foo
                |diff --git a/src/Bar.kt b/src/Bar.kt
                |index 3333333..4444444 100644
                |--- a/src/Bar.kt
                |+++ b/src/Bar.kt
                |@@ -1,3 +1,3 @@
                | package com.example
                |-class Bar
                |+class Bar(val name: String)
            """.trimMargin()

            val result = diffService.buildFilteredDiff(rawDiff, setOf("src/Foo.kt"))

            assertTrue(result.contains("src/Foo.kt"))
            assertFalse(result.contains("src/Bar.kt"))
        }

        @Test
        fun `should return empty string when no files match`() {
            val rawDiff = """
                |diff --git a/src/Foo.kt b/src/Foo.kt
                |index 1111111..2222222 100644
                |--- a/src/Foo.kt
                |+++ b/src/Foo.kt
                |@@ -1,3 +1,4 @@
                | package com.example
                |+import java.io.File
                | class Foo
            """.trimMargin()

            val result = diffService.buildFilteredDiff(rawDiff, setOf("src/NonExistent.kt"))

            assertEquals("", result)
        }
    }

    private fun createPrFile(
        filename: String,
        status: String = "modified",
        additions: Int = 10,
        deletions: Int = 5,
    ) = PrFile(
        sha = "abc123",
        filename = filename,
        status = status,
        additions = additions,
        deletions = deletions,
        changes = additions + deletions,
    )
}

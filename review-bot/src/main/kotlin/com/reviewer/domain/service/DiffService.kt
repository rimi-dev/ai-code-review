package com.reviewer.domain.service

import com.reviewer.config.properties.ReviewProperties
import com.reviewer.infrastructure.git.dto.PrFile
import io.github.oshai.kotlinlogging.KotlinLogging
import org.springframework.stereotype.Service

private val logger = KotlinLogging.logger {}

@Service
class DiffService(
    private val reviewProperties: ReviewProperties,
) {

    data class ParsedDiff(
        val files: List<DiffFile>,
        val totalLines: Int,
        val truncated: Boolean = false,
    )

    data class DiffFile(
        val path: String,
        val hunks: List<DiffHunk>,
        val additions: Int,
        val deletions: Int,
    )

    data class DiffHunk(
        val header: String,
        val startLineOld: Int,
        val startLineNew: Int,
        val lines: List<DiffLine>,
    )

    data class DiffLine(
        val content: String,
        val type: LineType,
        val oldLineNumber: Int?,
        val newLineNumber: Int?,
    )

    enum class LineType {
        CONTEXT,
        ADDITION,
        DELETION,
        HEADER,
    }

    fun parseDiff(rawDiff: String): ParsedDiff {
        val files = mutableListOf<DiffFile>()
        var totalLines = 0
        var truncated = false

        val fileSections = rawDiff.split(Regex("(?=^diff --git)", RegexOption.MULTILINE))
            .filter { it.isNotBlank() }

        for (section in fileSections) {
            val pathMatch = Regex("^diff --git a/(.+?) b/(.+?)$", RegexOption.MULTILINE)
                .find(section)
            val filePath = pathMatch?.groupValues?.get(2) ?: continue

            val hunks = mutableListOf<DiffHunk>()
            var additions = 0
            var deletions = 0

            val hunkPattern = Regex("^@@ -(\\d+)(?:,\\d+)? \\+(\\d+)(?:,\\d+)? @@(.*)$", RegexOption.MULTILINE)
            val hunkMatches = hunkPattern.findAll(section).toList()

            for ((hunkIdx, hunkMatch) in hunkMatches.withIndex()) {
                val startLineOld = hunkMatch.groupValues[1].toInt()
                val startLineNew = hunkMatch.groupValues[2].toInt()
                val header = hunkMatch.value

                val hunkStart = hunkMatch.range.last + 1
                val hunkEnd = if (hunkIdx + 1 < hunkMatches.size) {
                    hunkMatches[hunkIdx + 1].range.first
                } else {
                    section.length
                }

                val hunkContent = if (hunkStart < section.length) {
                    section.substring(hunkStart, minOf(hunkEnd, section.length))
                } else {
                    ""
                }

                val lines = mutableListOf<DiffLine>()
                var currentOld = startLineOld
                var currentNew = startLineNew

                for (line in hunkContent.lines()) {
                    if (line.isEmpty()) continue
                    totalLines++

                    if (totalLines > reviewProperties.maxDiffLines) {
                        truncated = true
                        break
                    }

                    when {
                        line.startsWith("+") -> {
                            lines.add(
                                DiffLine(
                                    content = line.substring(1),
                                    type = LineType.ADDITION,
                                    oldLineNumber = null,
                                    newLineNumber = currentNew,
                                ),
                            )
                            additions++
                            currentNew++
                        }
                        line.startsWith("-") -> {
                            lines.add(
                                DiffLine(
                                    content = line.substring(1),
                                    type = LineType.DELETION,
                                    oldLineNumber = currentOld,
                                    newLineNumber = null,
                                ),
                            )
                            deletions++
                            currentOld++
                        }
                        line.startsWith("\\") -> {
                            // "\ No newline at end of file" - skip
                        }
                        else -> {
                            val contextContent = if (line.startsWith(" ")) line.substring(1) else line
                            lines.add(
                                DiffLine(
                                    content = contextContent,
                                    type = LineType.CONTEXT,
                                    oldLineNumber = currentOld,
                                    newLineNumber = currentNew,
                                ),
                            )
                            currentOld++
                            currentNew++
                        }
                    }
                }

                hunks.add(
                    DiffHunk(
                        header = header,
                        startLineOld = startLineOld,
                        startLineNew = startLineNew,
                        lines = lines,
                    ),
                )

                if (truncated) break
            }

            files.add(
                DiffFile(
                    path = filePath,
                    hunks = hunks,
                    additions = additions,
                    deletions = deletions,
                ),
            )

            if (truncated) break
        }

        logger.debug { "Parsed diff: ${files.size} files, $totalLines lines, truncated=$truncated" }
        return ParsedDiff(files = files, totalLines = totalLines, truncated = truncated)
    }

    fun filterFiles(
        files: List<PrFile>,
        excludePatterns: List<String>,
    ): List<PrFile> {
        val allPatterns = reviewProperties.excludePatterns + excludePatterns

        return files.filter { file ->
            val excluded = allPatterns.any { pattern ->
                matchesGlob(file.filename, pattern)
            }
            if (excluded) {
                logger.debug { "Excluding file: ${file.filename}" }
            }
            !excluded
        }.take(reviewProperties.maxFiles)
    }

    fun buildFilteredDiff(
        rawDiff: String,
        allowedFiles: Set<String>,
    ): String {
        val fileSections = rawDiff.split(Regex("(?=^diff --git)", RegexOption.MULTILINE))
            .filter { it.isNotBlank() }

        return fileSections.filter { section ->
            val pathMatch = Regex("^diff --git a/(.+?) b/(.+?)$", RegexOption.MULTILINE)
                .find(section)
            val filePath = pathMatch?.groupValues?.get(2)
            filePath != null && filePath in allowedFiles
        }.joinToString("\n")
    }

    private fun matchesGlob(filename: String, pattern: String): Boolean {
        val regexPattern = pattern
            .replace(".", "\\.")
            .replace("*", ".*")
            .replace("?", ".")
        return Regex(regexPattern).containsMatchIn(filename)
    }
}

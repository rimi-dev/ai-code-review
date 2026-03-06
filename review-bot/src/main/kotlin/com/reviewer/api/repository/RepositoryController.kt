package com.reviewer.api.repository

import com.reviewer.api.dto.request.RegisterRepositoryRequest
import com.reviewer.api.dto.request.UpdateRepositoryRequest
import com.reviewer.api.dto.response.RepositoryResponse
import com.reviewer.api.exception.ApiException
import com.reviewer.domain.model.RegisteredRepository
import com.reviewer.domain.model.ReviewConfig
import com.reviewer.domain.repository.RegisteredRepositoryRepository
import io.github.oshai.kotlinlogging.KotlinLogging
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import org.springframework.http.HttpStatus
import org.springframework.web.bind.annotation.DeleteMapping
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.PutMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.ResponseStatus
import org.springframework.web.bind.annotation.RestController

private val logger = KotlinLogging.logger {}

@RestController
@RequestMapping("/api/v1/repositories")
class RepositoryController(
    private val registeredRepositoryRepository: RegisteredRepositoryRepository,
) {

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    suspend fun registerRepository(
        @RequestBody request: RegisterRepositoryRequest,
    ): RepositoryResponse {
        logger.info { "Registering repository: ${request.fullName}" }

        if (registeredRepositoryRepository.existsByFullName(request.fullName)) {
            throw ApiException(
                status = HttpStatus.CONFLICT,
                message = "Repository already registered: ${request.fullName}",
                errorCode = "repository_already_registered",
            )
        }

        val parts = request.fullName.split("/", limit = 2)
        if (parts.size != 2) {
            throw ApiException(
                status = HttpStatus.BAD_REQUEST,
                message = "Invalid repository full name format. Expected: owner/repo",
                errorCode = "invalid_repository_name",
            )
        }

        val entity = RegisteredRepository(
            fullName = request.fullName,
            owner = parts[0],
            name = parts[1],
            installationId = request.installationId,
            reviewConfig = request.reviewConfig ?: ReviewConfig(),
        )

        val saved = registeredRepositoryRepository.save(entity)
        return RepositoryResponse.from(saved)
    }

    @GetMapping
    fun listRepositories(): Flow<RepositoryResponse> {
        return registeredRepositoryRepository.findAll()
            .map { RepositoryResponse.from(it) }
    }

    @GetMapping("/{id}")
    suspend fun getRepository(@PathVariable id: String): RepositoryResponse {
        val entity = registeredRepositoryRepository.findById(id)
            ?: throw ApiException(
                status = HttpStatus.NOT_FOUND,
                message = "Repository not found: $id",
                errorCode = "repository_not_found",
            )
        return RepositoryResponse.from(entity)
    }

    @PutMapping("/{id}")
    suspend fun updateRepository(
        @PathVariable id: String,
        @RequestBody request: UpdateRepositoryRequest,
    ): RepositoryResponse {
        val existing = registeredRepositoryRepository.findById(id)
            ?: throw ApiException(
                status = HttpStatus.NOT_FOUND,
                message = "Repository not found: $id",
                errorCode = "repository_not_found",
            )

        val updated = existing.copy(
            enabled = request.enabled ?: existing.enabled,
            reviewConfig = request.reviewConfig ?: existing.reviewConfig,
        )

        val saved = registeredRepositoryRepository.save(updated)
        logger.info { "Updated repository: ${saved.fullName}" }
        return RepositoryResponse.from(saved)
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    suspend fun deleteRepository(@PathVariable id: String) {
        val existing = registeredRepositoryRepository.findById(id)
            ?: throw ApiException(
                status = HttpStatus.NOT_FOUND,
                message = "Repository not found: $id",
                errorCode = "repository_not_found",
            )

        registeredRepositoryRepository.delete(existing)
        logger.info { "Deleted repository: ${existing.fullName}" }
    }
}

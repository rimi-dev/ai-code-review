package com.reviewer.api.repository

import com.reviewer.api.dto.CreateRepositoryRequest
import com.reviewer.api.dto.RepositoryResponse
import com.reviewer.api.dto.UpdateRepositoryRequest
import com.reviewer.api.dto.UpdateReviewRulesRequest
import com.reviewer.api.exception.ApiException
import com.reviewer.domain.model.RegisteredRepository
import com.reviewer.domain.model.RepositorySettings
import com.reviewer.domain.repository.RegisteredRepositoryRepository
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.toList
import org.springframework.http.HttpStatus
import org.springframework.web.bind.annotation.DeleteMapping
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.PutMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController
import java.time.Instant

@RestController
@RequestMapping("/api/v1/repositories")
class RepositoryController(
    private val repositoryRepository: RegisteredRepositoryRepository,
) {
    @PostMapping
    suspend fun create(@RequestBody request: CreateRepositoryRequest): RepositoryResponse {
        val (owner, name) = request.fullName.split("/").let {
            if (it.size == 2) it[0] to it[1]
            else throw ApiException(HttpStatus.BAD_REQUEST, "fullName must be owner/repo format")
        }

        val repo = RegisteredRepository(
            fullName = request.fullName,
            owner = owner,
            name = name,
            installationId = request.installationId,
            webhookSecret = request.webhookSecret,
            accessToken = request.accessToken,
            settings = request.settings ?: RepositorySettings(),
            modelPreference = request.modelPreference ?: "auto",
            createdAt = Instant.now(),
        )
        val saved = repositoryRepository.save(repo)
        return RepositoryResponse.from(saved)
    }

    @GetMapping
    suspend fun list(): List<RepositoryResponse> {
        return repositoryRepository.findAll().map { RepositoryResponse.from(it) }.toList()
    }

    @GetMapping("/{id}")
    suspend fun get(@PathVariable id: String): RepositoryResponse {
        val repo = repositoryRepository.findById(id)
            ?: throw ApiException(HttpStatus.NOT_FOUND, "Repository not found")
        return RepositoryResponse.from(repo)
    }

    @PutMapping("/{id}")
    suspend fun update(@PathVariable id: String, @RequestBody request: UpdateRepositoryRequest): RepositoryResponse {
        val repo = repositoryRepository.findById(id)
            ?: throw ApiException(HttpStatus.NOT_FOUND, "Repository not found")

        val updated = repo.copy(
            isActive = request.isActive ?: repo.isActive,
            settings = request.settings ?: repo.settings,
            modelPreference = request.modelPreference ?: repo.modelPreference,
            updatedAt = Instant.now(),
        )
        val saved = repositoryRepository.save(updated)
        return RepositoryResponse.from(saved)
    }

    @DeleteMapping("/{id}")
    suspend fun delete(@PathVariable id: String) {
        repositoryRepository.deleteById(id)
    }

    @PutMapping("/{id}/rules")
    suspend fun updateRules(
        @PathVariable id: String,
        @RequestBody request: UpdateReviewRulesRequest,
    ): RepositoryResponse {
        val repo = repositoryRepository.findById(id)
            ?: throw ApiException(HttpStatus.NOT_FOUND, "Repository not found")

        val updated = repo.copy(
            reviewRules = request.rules,
            updatedAt = Instant.now(),
        )
        val saved = repositoryRepository.save(updated)
        return RepositoryResponse.from(saved)
    }
}

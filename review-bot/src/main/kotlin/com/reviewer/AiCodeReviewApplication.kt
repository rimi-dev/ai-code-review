package com.reviewer

import org.springframework.boot.autoconfigure.SpringBootApplication
import org.springframework.boot.context.properties.ConfigurationPropertiesScan
import org.springframework.boot.runApplication

@SpringBootApplication
@ConfigurationPropertiesScan
class AiCodeReviewApplication

fun main(args: Array<String>) {
    runApplication<AiCodeReviewApplication>(*args)
}

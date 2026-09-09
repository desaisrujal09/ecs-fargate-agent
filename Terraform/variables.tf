variable "container_cpu" {
  type    = number
  default = 256
}

variable "container_memory" {
  type    = number
  default = 512
}

variable "slack_bot_token" {
  type        = string
  sensitive   = true
}
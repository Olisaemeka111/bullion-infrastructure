###############################################################################
# Global DNS load balancing (north-south) — ACTIVE-ACTIVE across the 3 clouds.
# A single hostname (e.g. app.example.com) resolves to ALL THREE cluster ingress
# load balancers at once, using Route 53 weighted records + per-endpoint health
# checks. Every cloud serves live traffic; when one cloud's ingress fails its
# health check, Route 53 stops returning it and traffic shifts to the survivors.
#
# This is the north-south complement to the Istio east-west mesh. Requires a
# Route 53 hosted zone; the ingress hostnames come from each cluster's
# istio-ingressgateway LoadBalancer (kubectl -n istio-system get svc).
###############################################################################

variable "zone_id" {
  description = "Existing Route 53 hosted zone id."
  type        = string
}

variable "record_name" {
  description = "FQDN to serve active-active, e.g. app.example.com."
  type        = string
}

variable "endpoints" {
  description = "Per-cloud ingress hostnames (the istio-ingressgateway external DNS)."
  type = map(object({
    hostname = string
    weight   = number
  }))
  # example:
  # {
  #   aws   = { hostname = "a1b2....elb.amazonaws.com", weight = 100 }
  #   gcp   = { hostname = "34.x.x.x.nip.io",           weight = 100 }
  #   azure = { hostname = "20.x.x.x.cloudapp.azure.com", weight = 100 }
  # }
}

resource "aws_route53_health_check" "ingress" {
  for_each          = var.endpoints
  fqdn              = each.value.hostname
  port              = 443
  type              = "HTTPS"
  resource_path     = "/healthz/ready"
  failure_threshold = 3
  request_interval  = 30
  tags              = { cloud = each.key }
}

resource "aws_route53_record" "active_active" {
  for_each = var.endpoints

  zone_id        = var.zone_id
  name           = var.record_name
  type           = "CNAME"
  ttl            = 30
  set_identifier = each.key

  weighted_routing_policy {
    weight = each.value.weight
  }

  health_check_id = aws_route53_health_check.ingress[each.key].id
  records         = [each.value.hostname]
}

output "fqdn" {
  value = var.record_name
}

output "health_check_ids" {
  value = { for k, hc in aws_route53_health_check.ingress : k => hc.id }
}

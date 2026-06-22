###############################################################################
# Azure — Azure AKS with a default node pool of `node_count` medium nodes.
# Networking: a dedicated VNet + subnet, Azure CNI dataplane with Calico network
# policy, and a system-assigned managed identity for the cluster.
###############################################################################

resource "azurerm_resource_group" "rg" {
  name     = "${var.cluster_name}-rg"
  location = var.location
  tags     = var.tags
}

resource "azurerm_virtual_network" "vnet" {
  name                = "${var.cluster_name}-vnet"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  address_space       = [var.vnet_cidr]
  tags                = var.tags
}

resource "azurerm_subnet" "nodes" {
  name                 = "${var.cluster_name}-nodes"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = [var.node_subnet_cidr]
}

resource "azurerm_kubernetes_cluster" "aks" {
  name                = var.cluster_name
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  dns_prefix          = var.cluster_name
  kubernetes_version  = var.kubernetes_version
  tags                = var.tags

  default_node_pool {
    name            = "default"
    node_count      = var.node_count
    vm_size         = var.node_vm_size
    vnet_subnet_id  = azurerm_subnet.nodes.id
    os_disk_size_gb = 50
  }

  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin = "azure"
    network_policy = "calico"
    service_cidr   = var.service_cidr
    dns_service_ip = var.dns_service_ip
  }
}

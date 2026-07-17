defmodule FluxTraderWeb.CoreComponents do
  @moduledoc """
  Core UI components.
  """
  use Phoenix.Component

  attr :flash, :map, required: true
  def flash_group(assigns) do
    ~H"""
    <div id="flash-group">
      <%= if info = @flash["info"] do %>
        <div class="flash flash-info" role="alert"><%= info %></div>
      <% end %>
      <%= if error = @flash["error"] do %>
        <div class="flash flash-error" role="alert"><%= error %></div>
      <% end %>
    </div>
    """
  end
end

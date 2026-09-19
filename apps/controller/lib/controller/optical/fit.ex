defmodule Controller.Optical.Fit do
  @moduledoc """
  A small Levenberg–Marquardt with a numeric Jacobian, for the optical fits.
  `residuals.(x)` returns a list of numbers; `lm/3` returns the parameters,
  the final residuals and the parameter covariance (σ² (JᵀJ)⁻¹), which is
  where the margins of error come from.
  """

  @type result :: %{x: [float], residuals: [float], cost: float, cov: [[float]] | nil, sigma: float, iterations: non_neg_integer}

  def lm(residuals, x0, opts \\ []) do
    max_iter = opts[:max_iter] || 80
    r0 = residuals.(x0)
    {x, r, cost, iters} = loop(residuals, x0, r0, cost(r0), 1.0e-3, 0, max_iter)
    n = length(r)
    p = length(x)
    sigma = if n > p, do: :math.sqrt(cost / (n - p)), else: 0.0
    j = jacobian(residuals, x, r)
    cov = with {:ok, inv} <- invert(jtj(j, p)), do: Enum.map(inv, fn row -> Enum.map(row, &(&1 * sigma * sigma)) end), else: (_ -> nil)
    %{x: x, residuals: r, cost: cost, cov: cov, sigma: sigma, iterations: iters}
  end

  @doc "1σ of parameter i from a covariance, or nil."
  def sd(nil, _i), do: nil
  def sd(cov, i), do: cov |> Enum.at(i) |> Enum.at(i) |> max(0.0) |> :math.sqrt()

  defp loop(_f, x, r, cost, _lambda, iter, max) when iter >= max or cost < 1.0e-12, do: {x, r, cost, iter}

  defp loop(f, x, r, cost, lambda, iter, max) do
    p = length(x)
    j = jacobian(f, x, r)
    a = jtj(j, p)
    g = for k <- 0..(p - 1), do: Enum.zip(Enum.map(j, &Enum.at(&1, k)), r) |> Enum.reduce(0.0, fn {jk, ri}, acc -> acc + jk * ri end)
    damped = a |> Enum.with_index() |> Enum.map(fn {row, i} -> List.update_at(row, i, &(&1 * (1 + lambda) + 1.0e-12)) end)

    case solve(damped, Enum.map(g, &(-&1))) do
      nil ->
        {x, r, cost, iter}

      step ->
        x1 = Enum.zip(x, step) |> Enum.map(fn {a, b} -> a + b end)
        r1 = f.(x1)
        c1 = cost(r1)

        cond do
          c1 < cost and Enum.all?(step, &(abs(&1) < 1.0e-8)) -> {x1, r1, c1, iter + 1}
          c1 < cost -> loop(f, x1, r1, c1, max(lambda / 3, 1.0e-9), iter + 1, max)
          lambda > 1.0e8 -> {x, r, cost, iter}
          true -> loop(f, x, r, cost, lambda * 5, iter + 1, max)
        end
    end
  end

  defp cost(r), do: Enum.reduce(r, 0.0, &(&2 + &1 * &1))

  # rows = residuals, columns = parameters
  defp jacobian(f, x, r0) do
    cols =
      x
      |> Enum.with_index()
      |> Enum.map(fn {xi, i} ->
        h = max(1.0e-6, abs(xi) * 1.0e-5)
        f.(List.update_at(x, i, &(&1 + h))) |> Enum.zip(r0) |> Enum.map(fn {a, b} -> (a - b) / h end)
      end)

    Enum.zip(cols) |> Enum.map(&Tuple.to_list/1)
  end

  defp jtj(j, p) do
    for a <- 0..(p - 1) do
      for b <- 0..(p - 1) do
        Enum.reduce(j, 0.0, fn row, acc -> acc + Enum.at(row, a) * Enum.at(row, b) end)
      end
    end
  end

  # Gauss–Jordan with partial pivoting; nil when singular
  def solve(a, b) do
    n = length(b)
    m = Enum.zip(a, b) |> Enum.map(fn {row, bi} -> row ++ [bi] end)

    result =
      Enum.reduce_while(0..(n - 1), m, fn i, m ->
        {prow, pidx} = m |> Enum.drop(i) |> Enum.with_index(i) |> Enum.max_by(fn {row, _} -> abs(Enum.at(row, i)) end)
        pv = Enum.at(prow, i)

        if abs(pv) < 1.0e-14 do
          {:halt, nil}
        else
          m = m |> List.replace_at(pidx, Enum.at(m, i)) |> List.replace_at(i, prow)
          prow = Enum.map(prow, &(&1 / pv))

          m =
            m
            |> Enum.with_index()
            |> Enum.map(fn {row, k} ->
              if k == i, do: prow, else: (fct = Enum.at(row, i); Enum.zip(row, prow) |> Enum.map(fn {x, y} -> x - fct * y end))
            end)

          {:cont, m}
        end
      end)

    result && Enum.map(result, &List.last/1)
  end

  def invert(a) do
    n = length(a)
    ident = for i <- 0..(n - 1), do: for(j <- 0..(n - 1), do: if(i == j, do: 1.0, else: 0.0))
    cols = for k <- 0..(n - 1), do: solve(a, Enum.map(ident, &Enum.at(&1, k)))

    if Enum.any?(cols, &is_nil/1),
      do: {:error, :singular},
      else: {:ok, cols |> Enum.zip() |> Enum.map(&Tuple.to_list/1)}
  end
end

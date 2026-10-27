from typing import Any
from graph import Graph, computed, dtype_bytes, _layer_macs, _layer_parameters


BN_BUFFERS_PER_CHANNEL = 2
FLOPS_PER_MAC = 2
BUFFER_DTYPE = "fp32"


def arithmetic_intensity(graph: Graph) -> dict[str, Any]:
    total_flops = 0
    bytes_moved = 0.0
    per_layer = {}
    layers = {ly.name: ly for ly in graph.layers}

    for i, ly in enumerate(graph.layers):
        buffer_bytes = 0.0
        total_flops += int(_layer_macs(ly) * FLOPS_PER_MAC)
        if ly.reads:
            in_dtype = layers[ly.reads[0]].act_dtype
        elif i > 0:
            in_dtype = graph.layers[i - 1].act_dtype
        elif i == 0:
            in_dtype = graph.precision

        if ly.kind == "add" and len(ly.reads) == 2:
            in_b = 2 * ly.in_elements * dtype_bytes(in_dtype)
        else:
            in_b = ly.in_elements * dtype_bytes(in_dtype)
        
        if ly.kind == "bn":
            buffer_bytes = BN_BUFFERS_PER_CHANNEL * ly.out_shape[0] * dtype_bytes(BUFFER_DTYPE)

        weight_bytes = _layer_parameters(ly) * dtype_bytes(ly.weight_dtype)
        output_bytes = float(ly.out_elements * dtype_bytes(ly.act_dtype))
        bytes_moved += float(in_b + weight_bytes + buffer_bytes + output_bytes)

        per_layer[ly.name] = {
            "flops": int(_layer_macs(ly) * FLOPS_PER_MAC),
            "bytes": float(in_b + weight_bytes + buffer_bytes + output_bytes),
            "intensity": round((_layer_macs(ly) * FLOPS_PER_MAC) / (in_b + weight_bytes + buffer_bytes + output_bytes), 4) if (in_b + weight_bytes + buffer_bytes + output_bytes) > 0 else 0.0
        }

    if bytes_moved == 0.0:
        intensity = 0.0
    else:
        intensity = round(total_flops / bytes_moved, 4)


    return computed(
        value = float(intensity),
        message = f"{graph.name}: FLOPs over bytes, every byte counted once ",
        per_layer = per_layer,
        total_flops = total_flops,
        total_bytes = bytes_moved,
        flops_per_mac = 2,
        cache_reuse_assumed = False,
        note = "no fusion and no cache reuse; both would lower the byte column"
    )
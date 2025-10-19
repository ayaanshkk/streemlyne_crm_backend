from diffusers import DiffusionPipeline

pipe = DiffusionPipeline.from_pretrained("lightx2v/Wan2.1-T2V-14B-CausVid")

prompt = "Astronaut in a jungle, cold color palette, muted colors, detailed, 8k"
image = pipe(prompt).images[0]